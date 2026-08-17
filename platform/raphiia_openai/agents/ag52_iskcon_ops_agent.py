"""AG-52 Iskcon Ops — operaciones entidad ISKCON (ent_iskcon). Reutiliza InnerOS existente."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.agents.iskcon_capabilities import ENTITY_ID, ISKCON_DOMAINS, PROJECT, capabilities_summary

AGENT_ID = "AG-52_ISKCON_OPS"

PANIHATI_COLLECTIONS = (
    "panihati_sponsors",
    "panihati_expenses",
    "panihati_tasks",
    "panihati_group_events",
    "panihati_knowledge_items",
)


def agent_iskcon_capabilities() -> dict[str, Any]:
    return {"ok": True, "agent_id": AGENT_ID, **capabilities_summary()}


def _count_entity_contacts() -> dict[str, int]:
    from raphiia_openai import whatsapp_contacts, whatsapp_mcp_bridge

    contacts = whatsapp_contacts.list_contacts(entity_id=ENTITY_ID, limit=500)
    ops = whatsapp_mcp_bridge.list_ops_contacts(entity_id=ENTITY_ID, limit=500)
    return {
        "contacts": len(contacts.get("contacts") or contacts.get("items") or []),
        "ops_contacts": len(ops.get("contacts") or ops.get("items") or []),
    }


def _panihati_counts() -> dict[str, int]:
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    out: dict[str, int] = {}
    for name in PANIHATI_COLLECTIONS:
        try:
            out[name] = db[name].estimated_document_count()
        except Exception:
            out[name] = 0
    return out


def _funding_iskcon() -> dict[str, Any]:
    from raphiia_openai import funding_registry

    programs = funding_registry.list_funding_programs(limit=50)
    iskcon_kw = ("iskcon", "ffl", "food for life", "panihati", "templo", "devot")
    matched = []
    for p in programs.get("programs") or []:
        blob = f"{p.get('name','')} {p.get('description','')} {' '.join(p.get('tags') or [])}".lower()
        if any(k in blob for k in iskcon_kw):
            matched.append({"name": p.get("name"), "status": p.get("status"), "tags": p.get("tags")})
    return {"total_programs": len(programs.get("programs") or []), "iskcon_related": matched[:15]}


def agent_iskcon_status() -> dict[str, Any]:
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    ops_open = db["ralfia_ops_tasks"].count_documents({
        "$or": [
            {"tags": {"$in": ["iskcon", "ISKCON", "ffl", "panihati"]}},
            {"title": {"$regex": "iskcon|ffl|panihati|food for life", "$options": "i"}},
            {"correlation_id": {"$regex": "iskcon", "$options": "i"}},
        ],
        "status": {"$nin": ["completed", "cancelled", "failed"]},
    })
    mem = db["ralfia_memory_items"].count_documents({"entities": ENTITY_ID})
    ffl_mem = db["ralfia_memory_items"].count_documents({
        "entities": ENTITY_ID,
        "tags": {"$in": ["ffl", "food_for_life", "rations"]},
    })
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "entity_id": ENTITY_ID,
        "ops_open": ops_open,
        "memory_items": mem,
        "ffl_log_entries": ffl_mem,
        "contacts": _count_entity_contacts(),
        "panihati": _panihati_counts(),
        "funding": _funding_iskcon(),
        "domains_ready": list(ISKCON_DOMAINS.keys()),
        "profile_mcp": "iskcon_ops",
    }


def agent_iskcon_domain(domain: str) -> dict[str, Any]:
    key = (domain or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "ffl": "food_for_life",
        "food_for_life": "food_for_life",
        "donations": "donations_fundraising",
        "festival": "festivals_events",
        "festivals": "festivals_events",
        "panihati": "festivals_events",
        "temple": "temple_operations",
        "templo": "temple_operations",
        "workshop": "workshops_education",
        "contacts": "community_contacts",
    }
    key = aliases.get(key, key)
    if key not in ISKCON_DOMAINS:
        return {"ok": False, "error": "unknown_domain", "allowed": list(ISKCON_DOMAINS.keys())}
    dom = ISKCON_DOMAINS[key]
    live: dict[str, Any] = {}
    if key == "festivals_events":
        live["panihati_counts"] = _panihati_counts()
    if key in ("food_for_life", "donations_fundraising"):
        live["funding"] = _funding_iskcon()
    if key == "community_contacts":
        live["contacts"] = _count_entity_contacts()
    return {"ok": True, "agent_id": AGENT_ID, "domain": key, **dom, "live": live}


def agent_iskcon_ffl_log(
    title: str,
    body: str,
    *,
    plates: int | None = None,
    location: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Registra distribución FFL en memoria existente (ralfia_memory_items)."""
    from raphiia_openai import daily_memory

    extra = []
    if plates is not None:
        extra.append(f"Platos: {plates}")
    if location.strip():
        extra.append(f"Lugar: {location.strip()}")
    full_body = body.strip()
    if extra:
        full_body = f"{full_body}\n\n" + "\n".join(extra) if full_body else "\n".join(extra)
    payload = {
        "type": "fact",
        "kind": "fact",
        "title": title or f"FFL — {location or 'distribución'}",
        "body": full_body,
        "visibility": "PROJECT",
        "privacy_scope": "PROJECT",
        "tags": ["iskcon", "ffl", "food_for_life", "rations"],
        "owner_id": "RAFAEL",
        "entities": [ENTITY_ID],
        "project": PROJECT,
        "actor": AGENT_ID,
        "metadata": {"plates": plates, "location": location},
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "agent_id": AGENT_ID, "would_save": payload}
    result = daily_memory.save_memory(payload)
    record_agent_run(AGENT_ID, action="ffl_log", summary=title[:40], project=PROJECT)
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, **result}


def agent_iskcon_ffl_timeline(limit: int = 20) -> dict[str, Any]:
    from raphiia_openai import daily_memory

    hits = daily_memory.search_memory({
        "query": "ffl rations food for life distribución",
        "limit": limit,
        "owner_id": "RAFAEL",
        "actor": "RAFAEL",
        "project": PROJECT,
    })
    items = []
    for item in hits.get("items") or []:
        tags = [str(t).lower() for t in (item.get("tags") or [])]
        if "ffl" in tags or "food_for_life" in tags or "rations" in tags:
            items.append({
                "title": item.get("title"),
                "created_at": item.get("created_at"),
                "body_preview": (item.get("body") or "")[:200],
                "metadata": item.get("metadata"),
            })
    return {"ok": True, "agent_id": AGENT_ID, "count": len(items), "timeline": items}


def agent_iskcon_contacts_summary(limit: int = 10) -> dict[str, Any]:
    from raphiia_openai import whatsapp_contacts

    contacts = whatsapp_contacts.list_contacts(entity_id=ENTITY_ID, limit=limit)
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "entity_id": ENTITY_ID,
        "counts": _count_entity_contacts(),
        "sample": (contacts.get("contacts") or contacts.get("items") or [])[:limit],
        "import_hint": "import_google_contacts_csv(path, entity_id='ent_iskcon', upsert_ops=True)",
    }


def agent_iskcon_dispatch(action: str, message: str = "", *, dry_run: bool = True) -> dict[str, Any]:
    action = (action or "status").strip().lower()
    if action == "status":
        return agent_iskcon_status()
    if action == "capabilities":
        return agent_iskcon_capabilities()
    if action in ("domain", "ffl", "festival", "temple", "contacts", "funding"):
        domain_map = {
            "ffl": "food_for_life",
            "festival": "festivals_events",
            "temple": "temple_operations",
            "contacts": "community_contacts",
            "funding": "donations_fundraising",
        }
        if action == "domain" and message.strip():
            return agent_iskcon_domain(message.strip())
        if action in domain_map:
            return agent_iskcon_domain(domain_map[action])
    if action == "ffl_log" and message.strip():
        parts = message.split("|", 2)
        title = parts[0].strip()
        body = parts[1].strip() if len(parts) > 1 else ""
        loc = parts[2].strip() if len(parts) > 2 else ""
        return agent_iskcon_ffl_log(title, body, location=loc, dry_run=dry_run)
    if action == "memory" and message.strip():
        from raphiia_openai import daily_memory
        if dry_run:
            return {"ok": True, "dry_run": True, "would_save": message[:200], "entity": ENTITY_ID}
        r = daily_memory.save_memory({
            "type": "summary",
            "kind": "summary",
            "title": f"ISKCON — {message[:60]}",
            "body": message,
            "visibility": "PROJECT",
            "privacy_scope": "PROJECT",
            "tags": ["iskcon"],
            "owner_id": "RAFAEL",
            "entities": [ENTITY_ID],
            "project": PROJECT,
            "actor": AGENT_ID,
        })
        record_agent_run(AGENT_ID, action="iskcon_memory", summary="saved", project=PROJECT)
        return {"ok": True, "agent_id": AGENT_ID, **r}
    if action == "ops" and message.strip() and not dry_run:
        from raphiia_openai import coordination_live
        return coordination_live.create_ops_task(
            title=f"ISKCON: {message[:80]}",
            assignee="cursor",
            priority="normal",
            from_agent=AGENT_ID,
            correlation_id=f"iskcon-ops-{ENTITY_ID}",
            related_project=PROJECT,
        )
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "action": action,
        "dry_run": dry_run,
        "allowed_actions": [
            "status", "capabilities", "domain", "ffl", "festival", "temple",
            "contacts", "funding", "ffl_log", "memory", "ops",
        ],
        "entity_id": ENTITY_ID,
    }
