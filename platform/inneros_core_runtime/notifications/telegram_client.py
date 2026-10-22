"""Telegram Bot API — Notificaciones paralelas independientes para el Owner."""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("inneros.notifications.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_NOTIFY_ENABLED = os.getenv("TELEGRAM_NOTIFY_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}


def _redact_token(url_or_text: str) -> str:
    """Evita filtrar tokens de bot en logs o errores."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token and token in url_or_text:
        return url_or_text.replace(token, "[REDACTED_TELEGRAM_TOKEN]")
    return url_or_text


def telegram_status() -> dict[str, Any]:
    """Reporta el estado del canal Telegram sin exponer secretos."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    enabled = os.getenv("TELEGRAM_NOTIFY_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}

    configured = bool(token and chat_id)
    return {
        "ok": configured and enabled,
        "channel": "telegram",
        "enabled": enabled,
        "configured": configured,
        "has_token": bool(token),
        "has_chat_id": bool(chat_id),
        "chat_id_hint": f"...{chat_id[-4:]}" if len(chat_id) >= 4 else None,
        "action_required": None if configured else "Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment or vault.",
    }


def send_telegram_message(
    text: str,
    chat_id: str | None = None,
    *,
    parse_mode: str | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Envía un mensaje directo vía Telegram Bot API de forma segura y desacoplada."""
    if not TELEGRAM_NOTIFY_ENABLED and os.getenv("TELEGRAM_NOTIFY_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {"ok": False, "skipped": True, "reason": "telegram_notifications_disabled"}

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    target_chat = (chat_id or os.getenv("TELEGRAM_CHAT_ID") or "").strip()

    if not token or not target_chat:
        return {
            "ok": False,
            "skipped": True,
            "reason": "credentials_not_configured",
            "missing": [k for k, v in [("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", target_chat)] if not v],
            "action_required": "Owner must create bot via @BotFather and set TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID.",
        }

    clean_text = str(text or "").strip()
    if not clean_text:
        return {"ok": False, "error": "empty_message"}

    endpoint = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": clean_text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "InnerOS-Telegram-Adapter/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            return {
                "ok": resp_data.get("ok", False),
                "channel": "telegram",
                "message_id": resp_data.get("result", {}).get("message_id"),
                "chat_id": target_chat,
            }
    except Exception as exc:
        err_msg = _redact_token(str(exc))
        logger.warning(f"Error sending Telegram notification: {err_msg}")
        return {
            "ok": False,
            "channel": "telegram",
            "error": err_msg,
            "error_type": type(exc).__name__,
        }


def send_alert_telegram(text: str) -> dict[str, Any]:
    """Envío de alerta operativa al Owner vía Telegram."""
    return send_telegram_message(text)
