"""Webhook Notion → RalfIA (eventos en tiempo real, verificación HMAC)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from raphiia_openai import mongo_store
from raphiia_openai.notion_bridge import _headers, _ok_or_error, NOTION_API_BASE
from raphiia_openai.settings import (
    MCP_PUBLIC_URL,
    NOTION_WEBHOOK_VERIFICATION_TOKEN,
    NOTION_WEBHOOK_WATCH_DB_IDS,
)

EVENTS_COL = "ralfia_notion_webhook_events"
CONFIG_COL = "ralfia_notion_webhook_config"

WATCHED_EVENTS = {
    "page.content_updated",
    "page.created",
    "page.properties_updated",
    "comment.created",
    "data_source.schema_updated",
    "database.schema_updated",
}


def notion_webhook_public_url() -> str:
    base = (MCP_PUBLIC_URL or "").rstrip("/")
    return f"{base}/notion/webhook" if base else ""


def get_notion_webhook_setup() -> dict[str, Any]:
    """Instrucciones y URL para configurar webhooks en notion.so/profile/integrations."""
    token_set = bool((NOTION_WEBHOOK_VERIFICATION_TOKEN or "").strip())
    cfg = mongo_store.get_db()[CONFIG_COL].find_one({"kind": "verification"}) or {}
    pending = (cfg.get("verification_token") or "").strip()
    watch = [x.strip() for x in (NOTION_WEBHOOK_WATCH_DB_IDS or "").split(",") if x.strip()]
    return {
        "ok": True,
        "webhook_url": notion_webhook_public_url(),
        "verification_token_in_env": token_set,
        "pending_verification_token": pending[:8] + "…" if pending and not token_set else None,
        "watched_database_ids": watch,
        "subscribed_event_types": sorted(WATCHED_EVENTS),
        "notion_ui_steps": [
            "Abre https://www.notion.so/profile/integrations → integración Make (RalfIA Bridge)",
            "Pestaña Webhooks → + Create subscription",
            f"URL: {notion_webhook_public_url()}",
            "Eventos: page.content_updated, page.created, comment.created (mínimo)",
            "Tras crear, Notion envía verification_token → cópialo de GET /raphiia-mcp/notion/webhook/pending",
            "Pega el token en Verify subscription en Notion",
            "Guarda el mismo token en .env como NOTION_WEBHOOK_VERIFICATION_TOKEN",
        ],
        "capabilities": {
            "realtime": "Notion empuja cambios; RalfIA hace GET API para contenido completo",
            "opinar": "add_notion_page_comment (API) tras procesar evento",
            "inboxes_otras_ias": "INBOX/OUTBOX locales vía MCP; en Notion solo si están como páginas/DB conectadas",
        },
        "mcp_vs_api": {
            "cursor_notion_mcp": "OAuth en Cursor — leer/navegar Notion (no es tu servidor)",
            "chatgpt_notion_connector": "Conector nativo Notion en ChatGPT (OAuth Notion)",
            "ralfia_bridge": "API token en servidor — push docs, webhooks, comentarios (este puente)",
        },
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verify_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    secret = (secret or "").strip()
    sig = (signature_header or "").strip()
    if not secret or not sig:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    # Notion envía sha256=<hex>
    provided = sig.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, provided)


def _store_event(payload: dict[str, Any], *, verified: bool) -> str:
    db = mongo_store.get_db()
    doc = {
        "received_at": _now(),
        "verified": verified,
        "type": payload.get("type") or payload.get("event") or "unknown",
        "entity": payload.get("entity") or {},
        "payload": payload,
        "processed": False,
    }
    db[EVENTS_COL].insert_one(doc)
    return str(doc.get("_id", ""))


def _save_pending_verification(token: str) -> None:
    mongo_store.get_db()[CONFIG_COL].update_one(
        {"kind": "verification"},
        {"$set": {"kind": "verification", "verification_token": token, "saved_at": _now()}},
        upsert=True,
    )


def _fetch_page(page_id: str) -> dict[str, Any]:
    pid = (page_id or "").replace("-", "").strip()
    if not pid:
        return {"ok": False, "error": "page_id_required"}
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{NOTION_API_BASE}/pages/{pid}", headers=_headers())
    return _ok_or_error(resp)


def _maybe_process_page_event(payload: dict[str, Any]) -> dict[str, Any]:
    entity = payload.get("entity") or {}
    page_id = entity.get("id") or (payload.get("data") or {}).get("id")
    if not page_id:
        return {"ok": False, "skipped": True, "reason": "no_page_id"}
    fetched = _fetch_page(str(page_id))
    if not fetched.get("ok"):
        return {"ok": False, "fetch_error": fetched}
    title = ""
    props = fetched.get("properties") or {}
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            title = "".join(p.get("plain_text", "") for p in prop.get("title") or [])
            break
    out = {
        "ok": True,
        "page_id": page_id,
        "title": title,
        "last_edited_time": fetched.get("last_edited_time"),
        "parent": fetched.get("parent"),
    }
    # Si parece buzón de agente, registrar para coordinación
    low = title.lower()
    if "inbox" in low or "outbox" in low or "conversación" in low or "conversacion" in low:
        mongo_store.get_db()["ralfia_notion_inbox_signals"].update_one(
            {"page_id": page_id},
            {"$set": {**out, "signal": "agent_mailbox", "synced_at": _now()}},
            upsert=True,
        )
        out["agent_mailbox"] = True
    return out


def handle_notion_webhook(
    raw_body: bytes,
    *,
    signature: str | None = None,
) -> dict[str, Any]:
    """Procesa POST de Notion (verificación o evento)."""
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "invalid_json", "http_status": 400}

    if not isinstance(payload, dict):
        return {"ok": False, "error": "invalid_payload", "http_status": 400}

    # Challenge de verificación (suscripción nueva)
    verification = payload.get("verification_token")
    if verification:
        _save_pending_verification(str(verification))
        _store_event(payload, verified=False)
        return {
            "ok": True,
            "kind": "verification",
            "message": "verification_token_received",
            "hint": "Copia el token en Notion UI → Verify, y en NOTION_WEBHOOK_VERIFICATION_TOKEN",
            "http_status": 200,
        }

    secret = (NOTION_WEBHOOK_VERIFICATION_TOKEN or "").strip()
    if secret:
        cfg = mongo_store.get_db()[CONFIG_COL].find_one({"kind": "verification"}) or {}
        if not secret and cfg.get("verification_token"):
            secret = str(cfg["verification_token"])
        if not _verify_signature(raw_body, signature, secret):
            return {"ok": False, "error": "invalid_signature", "http_status": 401}

    event_type = str(payload.get("type") or payload.get("event") or "")
    _store_event(payload, verified=bool(secret))
    result: dict[str, Any] = {"ok": True, "kind": "event", "event_type": event_type, "http_status": 200}

    if event_type in {"page.content_updated", "page.created", "page.properties_updated"}:
        result["page"] = _maybe_process_page_event(payload)
        entity = payload.get("entity") or {}
        page_id = entity.get("id") or (result.get("page") or {}).get("page_id")
        last_ed = (result.get("page") or {}).get("last_edited_time") or ""
        page_parent = (result.get("page") or {}).get("parent") or entity.get("parent") or {}
        db_parent = page_parent.get("database_id")
        try:
            from raphiia_openai import notion_coordination

            if notion_coordination._db_id() and page_id:
                result["coordination"] = notion_coordination.process_coordination_page_event(
                    event_type=event_type,
                    page_id=str(page_id),
                    last_edited_time=last_ed,
                    database_id=str(db_parent or ""),
                )
        except Exception as exc:
            result["coordination_error"] = str(exc)
        try:
            from raphiia_openai.notion_projects_sync import _db08_id

            db_parent_norm = (db_parent or "").replace("-", "")
            if db_parent_norm == _db08_id().replace("-", ""):
                from raphiia_openai.notion_projects_sync import sync_creator_os_projects

                result["creator_os_sync"] = sync_creator_os_projects(dry_run=False, limit=5)
        except Exception as exc:
            result["creator_os_sync_error"] = str(exc)

    if event_type == "comment.created":
        result["comment"] = {"received": True, "entity": payload.get("entity")}

    mongo_store.log_sync("notion_webhook_event", event_type=event_type)
    return result


def get_pending_verification_token() -> dict[str, Any]:
    cfg = mongo_store.get_db()[CONFIG_COL].find_one({"kind": "verification"}) or {}
    token = (cfg.get("verification_token") or "").strip()
    if not token:
        return {"ok": False, "message": "Aún no llegó verification_token — crea la suscripción en Notion primero"}
    return {"ok": True, "verification_token": token, "saved_at": cfg.get("saved_at")}


def list_notion_webhook_events(limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    items = list(
        db[EVENTS_COL].find({}, {"payload": 0, "_id": 0})
        .sort("received_at", -1)
        .limit(max(1, min(limit, 100)))
    )
    return {"ok": True, "count": len(items), "items": items}
