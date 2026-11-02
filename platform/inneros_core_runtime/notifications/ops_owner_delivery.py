"""Multi-channel owner delivery: Telegram → WhatsApp → Email (+ optional voice)."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.notifications import telegram_client as tg
from raphiia_openai.notifications.evolution_client import send_alert_whatsapp


def _channels() -> list[str]:
    raw = (os.getenv("NOTIFY_OPS_CHANNELS") or "telegram,whatsapp,email").strip().lower()
    return [c.strip() for c in raw.split(",") if c.strip()]


def deliver_text(
    body: str,
    *,
    kind: str,
    dedupe_key: str,
    force: bool = False,
    inline_ops_task_id: str | None = None,
    fanout: bool = False,
) -> dict[str, Any]:
    """Deliver to configured channels. fanout=True hits every channel (HA handled elsewhere)."""
    if fanout:
        return deliver_text_fanout(
            body,
            kind=kind,
            dedupe_key=dedupe_key,
            inline_ops_task_id=inline_ops_task_id,
        )
    results: dict[str, Any] = {"ok": False, "channels": {}, "kind": kind}
    markup = tg.ops_auth_inline_keyboard(inline_ops_task_id) if inline_ops_task_id else None
    for ch in _channels():
        if ch == "telegram" and tg.telegram_enabled():
            r = tg.send_message(body, reply_markup=markup, parse_mode="Markdown")
            results["channels"]["telegram"] = r
            if r.get("ok"):
                results["ok"] = True
                results["via"] = "telegram"
                return results
        elif ch == "whatsapp" and os.getenv("INNEROS_WHATSAPP_NOTIFICATIONS", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            r = send_alert_whatsapp(body, prefix_node=True)
            results["channels"]["whatsapp"] = r
            if r.get("ok"):
                results["ok"] = True
                results["via"] = "whatsapp"
                return results
        elif ch == "email":
            from inneros_core_runtime.notifications.ops_task_alerts import (
                _notify_ops_auth_email_fallback,
            )

            r = _notify_ops_auth_email_fallback(
                {"task_id": inline_ops_task_id or dedupe_key},
                body=body,
                provider="ops",
                tid=str(inline_ops_task_id or dedupe_key),
            )
            results["channels"]["email"] = r
            if r.get("ok"):
                results["ok"] = True
                results["via"] = "email"
                return results
        elif ch == "voice":
            from inneros_core_runtime.owner_voice_alert import place_owner_voice_alert

            r = place_owner_voice_alert(body, kind=kind)
            results["channels"]["voice"] = r
            if r.get("ok"):
                results["ok"] = True
                results["via"] = "voice"
                return results
    return results


def deliver_text_fanout(
    body: str,
    *,
    kind: str,
    dedupe_key: str,
    inline_ops_task_id: str | None = None,
) -> dict[str, Any]:
    """Best-effort all channels (Telegram + email; WhatsApp only if enabled)."""
    results: dict[str, Any] = {"ok": False, "channels": {}, "kind": kind, "fanout": True}
    markup = tg.ops_auth_inline_keyboard(inline_ops_task_id) if inline_ops_task_id else None
    for ch in _channels():
        if ch == "telegram" and tg.telegram_enabled():
            results["channels"]["telegram"] = tg.send_message(
                body, reply_markup=markup, parse_mode="Markdown"
            )
        elif ch == "whatsapp" and os.getenv("INNEROS_WHATSAPP_NOTIFICATIONS", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            results["channels"]["whatsapp"] = send_alert_whatsapp(body, prefix_node=True)
        elif ch == "email":
            from inneros_core_runtime.notifications.ops_task_alerts import (
                _notify_ops_auth_email_fallback,
            )

            results["channels"]["email"] = _notify_ops_auth_email_fallback(
                {"task_id": inline_ops_task_id or dedupe_key},
                body=body,
                provider="ops",
                tid=str(inline_ops_task_id or dedupe_key),
            )
    results["ok"] = any(bool((v or {}).get("ok")) for v in results["channels"].values())
    via = [k for k, v in results["channels"].items() if (v or {}).get("ok")]
    results["via"] = "+".join(via) if via else None
    return results


def deliver_ops_auth(body: str, *, task_id: str, provider: str) -> dict[str, Any]:
    return deliver_text(
        body,
        kind="owner_auth",
        dedupe_key=task_id,
        inline_ops_task_id=task_id,
    )
