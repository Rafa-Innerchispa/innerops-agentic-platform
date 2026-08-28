"""Notion DB «RalfIA Coordination» — órdenes humanas ↔ ops_tasks ↔ respuestas."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx

from raphiia_openai import mongo_store
from raphiia_openai.notion_bridge import (
    NOTION_API_BASE,
    _headers,
    _ok_or_error,
    add_notion_page_comment,
)
from raphiia_openai.settings import (
    NOTION_COORDINATION_DATABASE_ID,
    NOTION_DOCS_PARENT_PAGE_ID,
)

DEDUPE_COL = "ralfia_notion_webhook_dedupe"
INDEX_COL = "ralfia_notion_coordination_index"

DB_TITLE = "RalfIA Coordination"

AGENT_DEST_OPTIONS = [
    {"name": "cursor", "color": "blue"},
    {"name": "codex", "color": "purple"},
    {"name": "antigravity", "color": "orange"},
    {"name": "chatgpt", "color": "green"},
    {"name": "gemini", "color": "yellow"},
    {"name": "notion", "color": "gray"},
    {"name": "ralfia", "color": "brown"},
    {"name": "rafael", "color": "pink"},
]

PRIORITY_OPTIONS = [
    {"name": "low", "color": "gray"},
    {"name": "normal", "color": "default"},
    {"name": "high", "color": "orange"},
    {"name": "critical", "color": "red"},
]

STATUS_OPTIONS = [
    {"name": "Pending", "color": "yellow"},
    {"name": "Dispatched", "color": "blue"},
    {"name": "In Progress", "color": "purple"},
    {"name": "Completed", "color": "green"},
    {"name": "Failed", "color": "red"},
    {"name": "Cancelled", "color": "gray"},
]

COORDINATION_DB_SCHEMA: dict[str, Any] = {
    "title": DB_TITLE,
    "title_property": "Asunto",
    "properties": {
        "agent_dest": {
            "type": "select",
            "select": {"options": AGENT_DEST_OPTIONS},
        },
        "priority": {
            "type": "select",
            "select": {"options": PRIORITY_OPTIONS},
        },
        "status": {
            "type": "select",
            "select": {"options": STATUS_OPTIONS},
        },
        "correlation_id": {"type": "rich_text", "rich_text": {}},
        "from_agent": {"type": "rich_text", "rich_text": {}},
        "body": {"type": "rich_text", "rich_text": {}},
        "ralfia_task_id": {"type": "rich_text", "rich_text": {}},
        "last_response": {"type": "rich_text", "rich_text": {}},
        "last_response_at": {"type": "date", "date": {}},
        "source": {
            "type": "select",
            "select": {
                "options": [
                    {"name": "notion_ui", "color": "default"},
                    {"name": "notion_webhook", "color": "blue"},
                    {"name": "mcp", "color": "green"},
                    {"name": "manual", "color": "gray"},
                ]
            },
        },
    },
}

# Contrato documentado (API + webhook)
EVENT_CONTRACT: dict[str, Any] = {
    "inbound_webhook_fields": {
        "type": "page.created | page.properties_updated | page.content_updated | comment.created",
        "entity.id": "page_id Notion (UUID)",
        "entity.parent.database_id": "debe coincidir con NOTION_COORDINATION_DATABASE_ID para órdenes",
        "data": "payload opcional según versión API",
    },
    "dedupe": {
        "key_formula": "sha256(event_type + '|' + page_id + '|' + last_edited_time)",
        "store": DEDUPE_COL,
        "ttl_hint": "eventos repetidos con mismo last_edited_time se ignoran",
        "fallback_event_id": "payload.id o hash del body si Notion no envía id",
    },
    "normalized_event": {
        "event_id": "string",
        "event_type": "string",
        "page_id": "string",
        "database_id": "string | null",
        "last_edited_time": "ISO8601",
        "dedupe_key": "sha256 hex",
    },
}

RESPONSE_CONTRACT: dict[str, Any] = {
    "strategy": "both",
    "on_dispatch": {
        "notion_status": "Dispatched",
        "notion_fields": ["ralfia_task_id", "status"],
        "comment": "RalfIA: orden ops_{id} creada → {agent_dest}",
    },
    "on_complete": {
        "notion_status": "Completed | Failed",
        "notion_fields": ["last_response", "last_response_at", "status"],
        "comment": "RalfIA [{status}]: resumen evidencia + correlation_id",
    },
    "canonical_store": "Mongo ralfia_ops_tasks + ralfia_notion_coordination_index",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_id() -> str:
    return (NOTION_COORDINATION_DATABASE_ID or "").strip()


def _prop_rt(value: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": str(value)[:1800]}}]}


def _prop_select(name: str) -> dict[str, Any]:
    return {"select": {"name": name}}


def _prop_date(iso: str) -> dict[str, Any]:
    return {"date": {"start": iso[:10]}}


def _extract_prop(prop: dict[str, Any]) -> Any:
    if not isinstance(prop, dict):
        return None
    t = prop.get("type")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title") or [])
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text") or [])
    if t == "select":
        return (prop.get("select") or {}).get("name")
    if t == "date":
        return (prop.get("date") or {}).get("start")
    return None


def get_notion_coordination_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "database_title": DB_TITLE,
        "database_id": _db_id() or None,
        "parent_page_id": NOTION_DOCS_PARENT_PAGE_ID or None,
        "schema": COORDINATION_DB_SCHEMA,
        "event_contract": EVENT_CONTRACT,
        "response_contract": RESPONSE_CONTRACT,
        "public_webhook": "https://sworn-profusely-alongside.ngrok-free.dev/raphiia-mcp/notion/webhook",
        "mcp_tools": [
            "bootstrap_notion_coordination_db",
            "get_notion_coordination_contract",
            "create_ops_task",
            "complete_ops_task",
        ],
    }


def bootstrap_notion_coordination_db(*, dry_run: bool = True) -> dict[str, Any]:
    parent = (NOTION_DOCS_PARENT_PAGE_ID or "").strip()
    if not parent:
        return {"ok": False, "error": "NOTION_DOCS_PARENT_PAGE_ID requerido"}
    if _db_id():
        return {
            "ok": True,
            "reused": True,
            "database_id": _db_id(),
            "message": "DB ya en .env NOTION_COORDINATION_DATABASE_ID",
            "contract": get_notion_coordination_contract(),
        }
    props: dict[str, Any] = {"Asunto": {"title": {}}}
    for name, spec in COORDINATION_DB_SCHEMA["properties"].items():
        props[name] = {spec["type"]: spec.get(spec["type"], {})}
    body = {
        "parent": {"type": "page_id", "page_id": parent},
        "title": [{"type": "text", "text": {"content": DB_TITLE}}],
        "properties": props,
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "would_create": body, "parent_page_id": parent}
    with httpx.Client(timeout=45) as client:
        resp = client.post(f"{NOTION_API_BASE}/databases", headers=_headers(), json=body)
    parsed = _ok_or_error(resp)
    if not parsed.get("ok"):
        return parsed
    return {
        "ok": True,
        "dry_run": False,
        "database_id": parsed.get("id"),
        "url": parsed.get("url"),
        "hint": "Copia database_id a NOTION_COORDINATION_DATABASE_ID en .env",
        "contract": get_notion_coordination_contract(),
    }


def compute_dedupe_key(*, event_type: str, page_id: str, last_edited_time: str) -> str:
    raw = f"{event_type}|{page_id}|{last_edited_time}"
    return hashlib.sha256(raw.encode()).hexdigest()


def is_duplicate_event(dedupe_key: str) -> bool:
    return mongo_store.get_db()[DEDUPE_COL].find_one({"dedupe_key": dedupe_key}) is not None


def mark_event_processed(dedupe_key: str, meta: dict[str, Any]) -> None:
    mongo_store.get_db()[DEDUPE_COL].update_one(
        {"dedupe_key": dedupe_key},
        {"$set": {**meta, "dedupe_key": dedupe_key, "processed_at": _now()}},
        upsert=True,
    )


def _fetch_page(page_id: str) -> dict[str, Any]:
    pid = (page_id or "").replace("-", "").strip()
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{NOTION_API_BASE}/pages/{pid}", headers=_headers())
    return _ok_or_error(resp)


def _patch_page(page_id: str, properties: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        resp = client.patch(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=_headers(),
            json={"properties": properties},
        )
    return _ok_or_error(resp)


def process_coordination_page_event(
    *,
    event_type: str,
    page_id: str,
    last_edited_time: str,
    database_id: str | None = None,
) -> dict[str, Any]:
    """Webhook → si página es RalfIA Coordination y status=Pending → create_ops_task."""
    coord_db = _db_id()
    if not coord_db:
        return {"ok": True, "skipped": True, "reason": "NOTION_COORDINATION_DATABASE_ID not set"}
    db_norm = (database_id or "").replace("-", "")
    if db_norm and db_norm != coord_db.replace("-", ""):
        return {"ok": True, "skipped": True, "reason": "not_coordination_db"}

    dedupe_key = compute_dedupe_key(
        event_type=event_type,
        page_id=page_id,
        last_edited_time=last_edited_time or _now(),
    )
    if is_duplicate_event(dedupe_key):
        return {"ok": True, "skipped": True, "reason": "duplicate", "dedupe_key": dedupe_key}

    fetched = _fetch_page(page_id)
    if not fetched.get("ok"):
        return {"ok": False, "error": "fetch_failed", "details": fetched}

    props = fetched.get("properties") or {}
    title = _extract_prop(props.get("Asunto", {})) or ""
    agent_dest = (_extract_prop(props.get("agent_dest", {})) or "").lower()
    priority = (_extract_prop(props.get("priority", {})) or "normal").lower()
    status = _extract_prop(props.get("status", {})) or ""
    body = _extract_prop(props.get("body", {})) or ""
    correlation_id = _extract_prop(props.get("correlation_id", {})) or ""
    from_agent = _extract_prop(props.get("from_agent", {})) or "NOTION"
    existing_task = _extract_prop(props.get("ralfia_task_id", {})) or ""

    if status and status not in ("Pending",):
        mark_event_processed(dedupe_key, {"page_id": page_id, "skipped_status": status})
        return {"ok": True, "skipped": True, "reason": f"status_{status}"}

    if existing_task:
        mark_event_processed(dedupe_key, {"page_id": page_id, "existing_task": existing_task})
        return {"ok": True, "skipped": True, "reason": "already_dispatched"}

    if not agent_dest:
        return {"ok": True, "skipped": True, "reason": "no_agent_dest"}

    if not correlation_id:
        correlation_id = f"notion-{secrets.token_hex(6)}"

    from raphiia_openai.coordination_live import create_ops_task

    task = create_ops_task(
        assignee=agent_dest,
        title=title or "Orden desde Notion",
        checklist=[body] if body else ["Ejecutar orden Notion"],
        evidence_required=["status OK/PARTIAL/FAIL", "evidence object"],
        priority=priority,
        from_agent=from_agent,
        correlation_id=correlation_id,
    )
    task_id = task.get("task_id", "")
    _patch_page(
        page_id,
        {
            "status": _prop_select("Dispatched"),
            "ralfia_task_id": _prop_rt(task_id),
            "correlation_id": _prop_rt(correlation_id),
            "source": _prop_select("notion_webhook"),
        },
    )
    add_notion_page_comment(
        page_id,
        f"RalfIA: orden `{task_id}` despachada → **{agent_dest}** (correlation `{correlation_id}`)",
    )

    mongo_store.get_db()[INDEX_COL].update_one(
        {"page_id": page_id},
        {
            "$set": {
                "page_id": page_id,
                "correlation_id": correlation_id,
                "task_id": task_id,
                "agent_dest": agent_dest,
                "title": title,
                "status": "Dispatched",
                "updated_at": _now(),
            }
        },
        upsert=True,
    )
    mark_event_processed(dedupe_key, {"page_id": page_id, "task_id": task_id})
    mongo_store.log_sync("notion_coordination_dispatch", page_id=page_id, task_id=task_id)
    return {"ok": True, "dispatched": True, "task_id": task_id, "correlation_id": correlation_id}


def post_response_to_notion(
    *,
    correlation_id: str,
    status: str,
    summary: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cierra loop Notion: campo last_response + comentario."""
    if not _db_id():
        return {"ok": False, "error": "NOTION_COORDINATION_DATABASE_ID not set"}
    db = mongo_store.get_db()
    rec = db[INDEX_COL].find_one({"correlation_id": correlation_id}) or db[INDEX_COL].find_one(
        {"task_id": correlation_id}
    )
    if not rec:
        # buscar por task_id en ops_tasks
        ops = db["ralfia_ops_tasks"].find_one({"correlation_id": correlation_id}, {"task_id": 1})
        if ops:
            rec = db[INDEX_COL].find_one({"task_id": ops.get("task_id")})
    if not rec or not rec.get("page_id"):
        return {"ok": False, "error": "notion_page_not_found_for_correlation"}

    page_id = rec["page_id"]
    st = status if status in ("Completed", "Failed", "Cancelled") else "Completed"
    summary = (summary or "")[:1800]
    _patch_page(
        page_id,
        {
            "status": _prop_select(st),
            "last_response": _prop_rt(summary),
            "last_response_at": _prop_date(_now()),
        },
    )
    ev = evidence or {}
    add_notion_page_comment(
        page_id,
        f"RalfIA [{st}]: {summary}\n\nevidence keys: {', '.join(ev.keys()) or '—'}",
    )
    db[INDEX_COL].update_one({"page_id": page_id}, {"$set": {"status": st, "last_response": summary, "updated_at": _now()}})
    return {"ok": True, "page_id": page_id, "status": st}
