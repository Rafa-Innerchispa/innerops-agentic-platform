"""AG-52 Iskcon Ops — operaciones entidad ISKCON (ent_iskcon). Reutiliza InnerOS existente."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.agents.iskcon_capabilities import ENTITY_ID, ISKCON_DOMAINS, PROJECT, capabilities_summary
from raphiia_openai import module_contract

AGENT_ID = "AG-52_ISKCON_OPS"
AGENT_VERSION = "2.1.0"
FABRIC_AGENT_ID = "AG-52"
WHATSAPP_YOGA_CHANNEL = "whatsapp_yoga"
SEND_POLICY = "draft_only_requires_owner_approval"

ISKCON_SOURCE_REFS = [
    {
        "source": "notion",
        "title": "01.6 — Sobre ISKCON Guayaquil",
        "id": "c1572269-4354-4b74-9c8e-8f97983f85d9",
        "use": "identity, mission, public contact, local context",
    },
    {
        "source": "notion",
        "title": "Sistema de Calendarios ISKCON — Guia para Guayaquil",
        "id": "c5a19358-f395-48cb-887a-285dcbd42ed9",
        "use": "weekly programs, flexible-event protocol, Vaishnava calendar governance",
    },
    {
        "source": "notion",
        "title": "Proyecto — Panihati (2025)",
        "id": "cefb7157-6229-4027-aaa6-135eb1645c83",
        "use": "festival planning, sponsor/volunteer content boundaries",
    },
    {
        "source": "website",
        "title": "ISKCON Guayaquil WordPress",
        "url": "https://www.iskconguayaquil.org/",
        "use": "public web presence and future publishing target",
    },
]

YOGA_DAILY_THEMES = [
    ("Respirar y recordar", "Empieza el dia con respiracion suave y unas rondas de maha-mantra. La practica es simple: volver la mente a Krishna con paciencia."),
    ("Gratitud antes de dormir", "Cierra el dia agradeciendo una oportunidad de servir. La gratitud vuelve el yoga algo vivo, no solo una postura."),
    ("Ahimsa en la mesa", "El yoga tambien se practica al elegir alimento ofrecido con amor. Prasadam educa el corazon en no violencia."),
    ("Servicio pequeno, cambio real", "Haz hoy un acto de seva: ayudar, ordenar, escuchar, cocinar o compartir. El servicio limpia lo que la mente complica."),
    ("Mantra para enfocar", "Cuando la mente se disperse, vuelve al sonido sagrado. Repetir con atencion vale mas que correr con ansiedad."),
    ("Bhagavad-gita aplicado", "Pregunta practica del dia: que accion puedo hacer con mas conciencia y menos ego? Ese tambien es yoga."),
    ("Kirtan como medicina", "Cantar juntos ordena la energia de la comunidad. Si puedes, comparte un kirtan breve con alguien hoy."),
    ("Yoga en familia", "Invita a alguien a respirar, escuchar o agradecer contigo. La vida espiritual crece mejor cuando se comparte con ternura."),
    ("Disciplina amable", "No busques perfeccion. Vuelve a tu practica con constancia: mantra, lectura, prasadam y servicio."),
    ("Cuerpo al servicio", "Cuida el cuerpo como instrumento de seva. Estirar, respirar y descansar tambien pueden ser ofrenda."),
    ("Comunidad espiritual", "Acercarse a buenos companeros fortalece la practica. Pregunta por clases, satsang o programas abiertos de la comunidad."),
    ("Meditacion en accion", "Antes de responder o decidir, haz una pausa. Esa pausa puede convertir una reaccion en conciencia."),
    ("Food for Life", "Compartir alimento espiritualizado une yoga y compasion. Servir prasadam es una forma directa de amor aplicado."),
    ("Invitacion semanal", "Los domingos hay programa abierto con kirtan, clase, arati y prasadam. Confirma siempre horarios oficiales antes de asistir."),
]

PANIHATI_COLLECTIONS = (
    "panihati_sponsors",
    "panihati_expenses",
    "panihati_tasks",
    "panihati_group_events",
    "panihati_knowledge_items",
)


def agent_iskcon_capabilities() -> dict[str, Any]:
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        **capabilities_summary(),
        "module_manifest": module_contract.get_module_manifest(ENTITY_ID, "iskcon_ops").get("manifest"),
    }


def agent_iskcon_module_manifest() -> dict[str, Any]:
    """Canonical module manifest consumed by ARIA, profiles and small local models."""
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        **module_contract.get_module_manifest(ENTITY_ID, "iskcon_ops"),
    }


def agent_iskcon_action(
    intent: str = "auto",
    message: str = "",
    inputs: dict[str, Any] | None = None,
    *,
    dry_run: bool = True,
    actor: str = AGENT_ID,
) -> dict[str, Any]:
    payload = dict(inputs or {})
    if message.strip() and "message" not in payload:
        payload["message"] = message.strip()
    return module_contract.route_module_action(
        tenant_id=ENTITY_ID,
        module_id="iskcon_ops",
        intent=intent,
        inputs=payload,
        actor=actor,
        dry_run=dry_run,
    )


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
        "agent_version": AGENT_VERSION,
        "fabric_agent_id": FABRIC_AGENT_ID,
        "invocation_ready": True,
        "sources": {"count": len(ISKCON_SOURCE_REFS), "refs": ISKCON_SOURCE_REFS},
        "whatsapp_yoga": {
            "channel": WHATSAPP_YOGA_CHANNEL,
            "frequency": "2_per_day",
            "send_policy": SEND_POLICY,
            "configured": "draft_contract_ready",
        },
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




def agent_iskcon_sources() -> dict[str, Any]:
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "entity_id": ENTITY_ID,
        "sources": ISKCON_SOURCE_REFS,
        "website": {
            "url": "https://www.iskconguayaquil.org/",
            "status": "reachable_last_checked_by_codex",
            "notes": [
                "WordPress public site is online.",
                "Public posts/events feeds were empty during last audit, so schedules must be confirmed from Notion/memory before publishing.",
            ],
        },
    }


def _message_has(message: str, *needles: str) -> bool:
    m = (message or "").lower()
    return any(n in m for n in needles)


def _classify_intent(action: str, message: str) -> str:
    raw_action = (action or "").strip().lower()
    if raw_action and raw_action not in ("auto", "intent", "message", "route"):
        return raw_action
    if not (message or "").strip():
        return "status"
    if _message_has(message, "cambio", "cambios", "clase", "clases", "horario", "novedad", "novedades", "avisar"):
        return "class_update"
    if _message_has(message, "whatsapp", "canal", "yoga", "vaishnava", "vaishnava", "mensajes diarios", "dos mensajes", "2 mensajes"):
        return "yoga_whatsapp"
    contract_intent = module_contract.classify_module_intent(message, raw_action)
    if contract_intent not in ("status", "documents"):
        return contract_intent
    if _message_has(message, "food for life", "ffl", "raciones", "prasadam", "prasadam"):
        return "ffl"
    if _message_has(message, "panihati", "festival", "ratha yatra", "evento"):
        return "festival"
    if _message_has(message, "contacto", "contactos", "donante", "voluntario", "voluntarios"):
        return "contacts"
    if _message_has(message, "memoria", "guardar", "recordar", "notion", "fuente"):
        return "memory"
    if _message_has(message, "tarea", "ops", "ticket", "asignar"):
        return "ops"
    return "capabilities"


def agent_iskcon_yoga_campaign(message: str = "", *, days: int = 7, dry_run: bool = True) -> dict[str, Any]:
    days = max(1, min(int(days or 7), 14))
    draft_count = days * 2
    drafts = []
    for idx in range(draft_count):
        title, body = YOGA_DAILY_THEMES[idx % len(YOGA_DAILY_THEMES)]
        drafts.append({
            "day": idx // 2 + 1,
            "slot": "morning" if idx % 2 == 0 else "evening",
            "title": title,
            "body": body,
            "channel": WHATSAPP_YOGA_CHANNEL,
            "status": "draft",
        })
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "agent_version": AGENT_VERSION,
        "action": "yoga_whatsapp_campaign",
        "dry_run": dry_run,
        "entity_id": ENTITY_ID,
        "channel": WHATSAPP_YOGA_CHANNEL,
        "frequency": "2_per_day",
        "draft_count": len(drafts),
        "send_ready": False,
        "requires_approval": True,
        "send_policy": SEND_POLICY,
        "requested_message": message,
        "sources": ISKCON_SOURCE_REFS,
        "class_change_template": _class_update_payload(message="", dry_run=True)["draft"],
        "drafts": drafts,
        "next_steps": [
            "Confirm official WhatsApp channel/group id before any scheduler is connected.",
            "Confirm class calendar source of truth before announcements are sent.",
            "Use dry_run=false only for saving approved drafts to an internal queue; no direct broadcast is performed by this helper.",
        ],
        "module_action": agent_iskcon_action(
            "whatsapp_draft",
            message,
            inputs={"message": message, "days": days, "channel": WHATSAPP_YOGA_CHANNEL},
            dry_run=True,
        ),
    }


def _class_update_payload(message: str, *, dry_run: bool) -> dict[str, Any]:
    draft = {
        "title": "Aviso de clase / programa ISKCON Guayaquil",
        "body": (
            "Hare Krishna. Aviso para la comunidad: [actividad] tendra un ajuste el [fecha]. "
            "Nuevo horario/lugar: [hora_lugar]. Motivo: [motivo]. "
            "Confirmaremos cualquier novedad por este canal. Gracias por su comprension y servicio."
        ),
        "fields_needed": ["actividad", "fecha", "hora_lugar", "motivo", "facilitador/opcional"],
        "protocol": "Cambios de talleres, FFL o programas locales se comunican 3-5 dias antes cuando sea posible; festividades fijas no se mueven sin gobierno devocional.",
    }
    if message.strip():
        draft["source_message"] = message.strip()
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "action": "class_update_draft",
        "dry_run": dry_run,
        "entity_id": ENTITY_ID,
        "send_ready": False,
        "requires_approval": True,
        "channel": WHATSAPP_YOGA_CHANNEL,
        "draft": draft,
        "sources": ISKCON_SOURCE_REFS,
    }


def agent_iskcon_class_update(message: str = "", *, dry_run: bool = True) -> dict[str, Any]:
    return _class_update_payload(message, dry_run=dry_run)


def agent_iskcon_artifact_download(artifact_id: str, tenant_id: str = ENTITY_ID) -> dict[str, Any]:
    return module_contract.download_module_artifact(tenant_id=tenant_id, artifact_id=artifact_id)


def agent_iskcon_dispatch(action: str, message: str = "", *, dry_run: bool = True) -> dict[str, Any]:
    action = _classify_intent(action, message)
    if action == "status":
        return agent_iskcon_status()
    if action == "capabilities":
        return agent_iskcon_capabilities()
    if action in ("sources", "source", "notion", "website"):
        return agent_iskcon_sources()
    if action in (
        "emergency_plan",
        "letter",
        "dossier",
        "sponsor_pipeline",
        "festival_budget",
        "food_for_life_report",
        "whatsapp_draft",
        "documents",
    ):
        return agent_iskcon_action(action, message, dry_run=dry_run)
    if action in ("yoga", "yoga_whatsapp", "whatsapp_yoga", "campaign", "campana", "campaña"):
        return agent_iskcon_yoga_campaign(message, dry_run=dry_run)
    if action in ("class_update", "classes", "clases", "novedad", "schedule_update"):
        return agent_iskcon_class_update(message, dry_run=dry_run)
    if action in ("domain", "ffl", "festival", "temple", "contacts", "funding", "education"):
        domain_map = {
            "ffl": "food_for_life",
            "festival": "festivals_events",
            "temple": "temple_operations",
            "contacts": "community_contacts",
            "funding": "donations_fundraising",
            "education": "workshops_education",
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
            return {"ok": True, "dry_run": True, "would_save": message[:200], "entity": ENTITY_ID, "sources": ISKCON_SOURCE_REFS}
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
    if action == "ops" and message.strip():
        payload = {
            "title": f"ISKCON: {message[:80]}",
            "assignee": "cursor",
            "priority": "normal",
            "from_agent": AGENT_ID,
            "correlation_id": f"iskcon-ops-{ENTITY_ID}",
            "related_project": PROJECT,
        }
        if dry_run:
            return {"ok": True, "dry_run": True, "agent_id": AGENT_ID, "would_create_ops": payload}
        from raphiia_openai import coordination_live
        return coordination_live.create_ops_task(**payload)
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "action": action,
        "dry_run": dry_run,
        "allowed_actions": [
            "status", "capabilities", "sources", "domain", "ffl", "festival", "temple",
            "contacts", "funding", "education", "yoga_whatsapp", "class_update",
            "emergency_plan", "letter", "dossier", "sponsor_pipeline", "festival_budget",
            "food_for_life_report", "whatsapp_draft", "documents", "ffl_log", "memory", "ops", "intent", "auto",
        ],
        "entity_id": ENTITY_ID,
        "module_manifest": "iskcon_ops",
    }
