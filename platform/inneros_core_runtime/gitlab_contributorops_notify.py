"""Entrega multicanal ContributorOps — WhatsApp con failover + correo owner."""

from __future__ import annotations

import os
from typing import Any

OWNER_EMAIL = os.environ.get("RALFIA_OWNER_ALERT_EMAIL", "rafagye@gmail.com").strip()


def deliver_owner_message(message: str, *, severity: str = "S2", dedupe_key: str | None = None) -> dict[str, Any]:
    """Intenta WhatsApp (primary→amd); si falla, correo SMTP vía email_accounts."""
    text = (message or "").strip()
    if not text:
        return {"ok": False, "error": "empty_message"}

    channels: dict[str, Any] = {}
    try:
        from raphiia_openai.notifications.evolution_client import send_alert_whatsapp

        wa = send_alert_whatsapp(text, prefix_node=True)
        channels["whatsapp"] = wa
        if wa.get("ok"):
            return {"ok": True, "channel": "whatsapp", "whatsapp": wa}
    except Exception as exc:
        channels["whatsapp"] = {"ok": False, "error": str(exc)[:200]}

    try:
        from raphiia_openai.notifications import email_client

        subject = f"[GitLab ContributorOps {severity}] {text[:90].replace(chr(10), ' ')}"
        mail = email_client.send_email(
            to_addr=OWNER_EMAIL,
            subject=subject,
            body=text,
            from_account="rlopez@pcdoctor.com.ec",
            idempotency_key=dedupe_key or f"contribops:{hash(text) & 0xFFFFFFFFFFFF}",
        )
        channels["email"] = mail
        if mail.get("ok"):
            return {"ok": True, "channel": "email", "email": mail, "whatsapp": channels.get("whatsapp")}
    except Exception as exc:
        channels["email"] = {"ok": False, "error": str(exc)[:200]}

    try:
        from raphiia_openai import mongo_store

        mongo_store.log_coordination(
            agent="GITLAB_CONTRIBUTOROPS",
            summary=text[:500],
            event="owner_notify_fallback",
            project="gitlab-contributorops",
            metadata={"severity": severity, "channels": channels, "dedupe_key": dedupe_key},
        )
    except Exception:
        pass
    return {"ok": False, "error": "all_channels_failed", "channels": channels}
