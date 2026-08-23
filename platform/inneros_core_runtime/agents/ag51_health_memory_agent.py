"""AG-51 Health Memory — historial de salud privado (PRIVATE_HEALTH)."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-51_HEALTH_MEMORY"
HEALTH_TAGS = frozenset({"salud", "health", "medico", "médico", "vitals"})


def agent_health_save(
    title: str,
    body: str,
    *,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    from raphiia_openai import daily_memory

    merged = list(dict.fromkeys([*(tags or []), "salud", "health"]))
    result = daily_memory.save_memory({
        "type": "fact",
        "kind": "fact",
        "title": title,
        "body": body,
        "visibility": "PRIVATE_HEALTH",
        "privacy_scope": "PRIVATE_HEALTH",
        "tags": merged,
        "owner_id": "RAFAEL",
        "actor": AGENT_ID,
        "entities": ["RAFAEL"],
    })
    record_agent_run(AGENT_ID, action="agent_health_save", summary=title[:40], project="health")
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, **result}


def agent_health_timeline(query: str = "", limit: int = 20) -> dict[str, Any]:
    from raphiia_openai import daily_memory

    q = query.strip() or "salud médico vitals"
    hits = daily_memory.search_memory({
        "query": q,
        "limit": limit,
        "owner_id": "RAFAEL",
        "actor": "RAFAEL",
        "allowed_privacy": ["PRIVATE_HEALTH"],
    })
    items = []
    for item in (hits.get("items") or hits.get("memories") or []):
        scope = item.get("privacy_scope") or item.get("visibility") or ""
        tags = [str(t).lower() for t in (item.get("tags") or [])]
        if scope == "PRIVATE_HEALTH" or HEALTH_TAGS.intersection(tags):
            items.append({
                "memory_id": item.get("memory_id") or item.get("_id"),
                "title": item.get("title"),
                "created_at": item.get("created_at"),
                "body_preview": (item.get("body") or "")[:200],
            })
    return {"ok": True, "agent_id": AGENT_ID, "count": len(items), "timeline": items}


def agent_health_summary() -> dict[str, Any]:
    tl = agent_health_timeline(limit=10)
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "entries": tl.get("count", 0),
        "recent": tl.get("timeline", [])[:5],
        "note": "Memoria privada — solo RAFAEL / scopes PRIVATE_HEALTH",
    }
