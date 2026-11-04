"""Read-only delivery transports for InnerOS owner approval notices.

These adapters ONLY notify. They never approve/deny anything, consume an
approval nonce, mutate an OPS task, or silently authorize paid actions.
A short-lived HTTPS request page with authenticated WebAuthn/passkey user
verification and atomic canonical coordination is required separately.

No external calls occur on import. No notification is sent unless invoked
by an authorized durable outbox worker with real credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable
from urllib.parse import urlsplit

_TASK_ID = re.compile(r"ops_[a-f0-9]{12}\Z")
_TOPIC = re.compile(r"[A-Za-z0-9_-]{4,128}\Z")


@dataclass(frozen=True)
class OwnerApprovalNotice:
    task_id: str
    title: str
    expires_at: datetime
    risk: str

    def validate(self) -> None:
        if not _TASK_ID.fullmatch(self.task_id):
            raise ValueError("invalid_ops_task_id")
        if not self.title or len(self.title) > 150:
            raise ValueError("invalid_title")
        if not self.expires_at.tzinfo or self.expires_at <= datetime.now(timezone.utc):
            raise ValueError("expired_or_naive_approval")
        if self.risk not in {"low", "medium", "high", "critical"}:
            raise ValueError("invalid_risk")


def _https_origin(url: str) -> str:
    parts = urlsplit(url.strip())
    if (parts.scheme != "https" or not parts.hostname or parts.username or
            parts.password or parts.fragment or parts.query or parts.path not in {"", "/"}):
        raise ValueError("https_origin_required")
    return url.rstrip("/")


def approval_links(notice: OwnerApprovalNotice, approval_origin: str) -> dict[str, str]:
    """Links are NOT authorizations. A server must authenticate each decision."""
    notice.validate()
    origin = _https_origin(approval_origin)
    path = f"{origin}/approvals/{notice.task_id}"
    return {
        "approve": path + "?intent=approve",
        "reject": path + "?intent=reject",
        "review": path,
    }


def _message(notice: OwnerApprovalNotice) -> str:
    notice.validate()
    expiry = notice.expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # No secrets or detailed operational commands in notification payloads.
    return (f"{notice.title}\nTarea: {notice.task_id} | Riesgo: {notice.risk}"
            f" | Caduca: {expiry}\nDecision solo tras autenticacion en InnerOS.")


def ntfy_payload(notice: OwnerApprovalNotice, *, topic: str,
                 approval_origin: str) -> dict[str, Any]:
    if not _TOPIC.fullmatch(topic):
        raise ValueError("invalid_private_topic")
    links = approval_links(notice, approval_origin)
    return {
        "topic": topic,
        "title": "InnerOS: solicitud de aprobacion",
        "message": _message(notice),
        "priority": 5 if notice.risk in {"high", "critical"} else 4,
        "actions": [
            {"action": "view", "label": "Aprobar", "url": links["approve"]},
            {"action": "view", "label": "Rechazar", "url": links["reject"]},
        ],
        "click": links["review"],
    }


def telegram_payload(notice: OwnerApprovalNotice, *, chat_id: str,
                     approval_origin: str) -> dict[str, Any]:
    # Bot account ID must be provisioned by its owner, never guessed.
    if not re.fullmatch(r"-?[0-9]{3,20}", str(chat_id)):
        raise ValueError("invalid_telegram_chat_id")
    links = approval_links(notice, approval_origin)
    return {
        "chat_id": str(chat_id),
        "text": "InnerOS | Solicitud de aprobacion\n" + _message(notice),
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": [[
            {"text": "Aprobar", "url": links["approve"]},
            {"text": "Rechazar", "url": links["reject"]},
        ]]},
    }


def send_ntfy(
    notice: OwnerApprovalNotice, *, server_origin: str, topic: str,
    approval_origin: str, access_token: str,
    post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Notification delivery only; requires self-hosted, authenticated HTTPS."""
    origin = _https_origin(server_origin)
    if not access_token.strip():
        return {"ok": False, "reason": "ntfy_token_not_configured"}
    payload = ntfy_payload(notice, topic=topic, approval_origin=approval_origin)
    if post is None:
        import httpx
        post = httpx.post
    try:
        resp = post(origin + "/", json=payload,
                    headers={"Authorization": "Bearer " + access_token,
                             "Content-Type": "application/json"},
                    timeout=8)
        accepted = 200 <= int(resp.status_code) < 300
        data = resp.json() if accepted else {}
        return {"ok": accepted, "channel": "ntfy",
                "http_status": int(resp.status_code),
                "provider_message_id": str(data.get("id") or "")[:100] if isinstance(data, dict) else "",
                "delivery": "provider_accepted" if accepted else "provider_rejected"}
    except Exception as exc:
        # Exception messages can contain tokens or URLs. Return type only.
        return {"ok": False, "channel": "ntfy",
                "reason": type(exc).__name__, "delivery": "unknown"}


def send_telegram(
    notice: OwnerApprovalNotice, *, chat_id: str, bot_token: str,
    approval_origin: str, post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Telegram is a backup delivery service, NEVER an approval authority."""
    if not bot_token.strip():
        return {"ok": False, "channel": "telegram", "reason": "telegram_bot_not_configured"}
    payload = telegram_payload(notice, chat_id=chat_id, approval_origin=approval_origin)
    if post is None:
        import httpx
        post = httpx.post
    try:
        resp = post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json=payload, timeout=8)
        data = resp.json()
        accepted = 200 <= int(resp.status_code) < 300 and bool(data.get("ok"))
        msg = (data.get("result") or {}) if accepted else {}
        return {"ok": accepted, "channel": "telegram",
                "provider_message_id": str(msg.get("message_id") or "")[:80],
                "delivery": "provider_accepted" if accepted else "provider_rejected"}
    except Exception as exc:
        return {"ok": False, "channel": "telegram",
                "reason": type(exc).__name__, "delivery": "unknown"}
