"""Revisa correos vía Swarm API (IMAP ya configurado en Mongo email_accounts)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from raphiia_openai.notifications.settings import SWARM_API_BASE


def poll_all_mailboxes() -> dict[str, Any]:
    """POST /api/v1/email/poll — clasifica importancia y envía WhatsApp si alta."""
    url = f"{SWARM_API_BASE}/api/v1/email/poll"
    started_at = datetime.now(timezone.utc)
    try:
        r = httpx.post(url, timeout=120.0)
        if r.is_success:
            body = r.json()
            from raphiia_openai.notifications import email_review

            reviewed = email_review.process_new_messages(
                started_at=started_at,
                new_count=int(body.get("new_messages") or 0),
            )
            return {
                "ok": True,
                **body,
                "swarm_alerts_sent": int(body.get("alerts_sent") or 0),
                "alerts_sent": int(reviewed.get("alerts_sent") or 0),
                "ralfia_review": reviewed,
            }
        return {"ok": False, "http_status": r.status_code, "error": r.text[:500]}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "hint": "¿Swarm :8100 activo?"}
