"""Monitor de correos — reutiliza Swarm IMAP (email_accounts + /email/poll)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from raphiia_openai import mongo_store
from raphiia_openai.notifications.email_poll import poll_all_mailboxes
from raphiia_openai.notifications.settings import SWARM_API_BASE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_monitored_accounts() -> dict[str, Any]:
    """Cuentas IMAP activas que revisa ralfia-notify (mismo Mongo que Swarm)."""
    db = mongo_store.get_db()
    settings = db.email_settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    accounts = list(
        db.email_accounts.find(
            {"enabled": True},
            {
                "_id": 0,
                "email_account_id": 1,
                "address": 1,
                "label": 1,
                "imap_host": 1,
                "last_uid": 1,
                "last_error": 1,
                "updated_at": 1,
            },
        ).sort("address", 1)
    )
    return {
        "ok": True,
        "count": len(accounts),
        "accounts": accounts,
        "notify_on_high": settings.get("notify_on_high", True),
        "whatsapp_numbers": settings.get("whatsapp_numbers") or [],
        "keywords_important": settings.get("keywords_important") or [],
        "swarm_api": SWARM_API_BASE,
    }


def list_recent_emails(
    *,
    importance: str | None = "alta",
    limit: int = 10,
    account_address: str | None = None,
) -> dict[str, Any]:
    """Últimos correos clasificados en Mongo (los que alimentan alertas WhatsApp)."""
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if importance:
        filt["importance"] = importance
    if account_address:
        filt["account_address"] = account_address.strip().lower()
    items = list(
        db.email_messages.find(
            filt,
            {
                "_id": 0,
                "mail_id": 1,
                "account_address": 1,
                "from_addr": 1,
                "subject": 1,
                "importance": 1,
                "importance_reason": 1,
                "whatsapp_sent": 1,
                "suggested_action": 1,
                "route_area": 1,
                "view_url": 1,
                "received_at": 1,
            },
        )
        .sort("received_at", -1)
        .limit(max(1, min(limit, 50)))
    )
    return {"ok": True, "count": len(items), "messages": items, "filter": filt}


def email_monitor_summary() -> dict[str, Any]:
    """Resumen para WhatsApp/MCP: cuentas + últimos alta + stats Swarm."""
    accounts = list_monitored_accounts()
    recent = list_recent_emails(importance="alta", limit=5)
    stats: dict[str, Any] = {}
    try:
        r = httpx.get(f"{SWARM_API_BASE}/api/v1/email/stats", timeout=15.0)
        if r.is_success:
            stats = r.json()
    except Exception as exc:
        stats = {"error": str(exc)[:200]}
    return {
        "ok": True,
        "accounts": accounts.get("accounts", []),
        "recent_high": recent.get("messages", []),
        "stats": stats,
        "poll_endpoint": f"{SWARM_API_BASE}/api/v1/email/poll",
    }


def trigger_email_poll() -> dict[str, Any]:
    """Fuerza revisión IMAP vía Swarm (clasifica y envía WhatsApp si alta)."""
    result = poll_all_mailboxes()
    mongo_store.log_coordination(
        agent="EMAIL_MONITOR",
        summary=f"Poll manual: {result.get('new_messages', 0)} nuevos, {result.get('alerts_sent', 0)} alertas",
        event="email_poll_manual",
        project="ralfia-notifications",
        metadata=result,
    )
    return result
