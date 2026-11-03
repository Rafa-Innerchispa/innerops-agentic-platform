"""Owner notifications: Telegram (P1) + HA companion (P2) + email (P3)."""

from __future__ import annotations

import os
from typing import Any

SUBJECT_PREFIX = "[InnerOS]"


def owner_email() -> str:
    raw = (
        os.getenv("RALFIA_OPS_AUTH_EMAIL_TO")
        or os.getenv("OWNER_NOTIFY_EMAIL")
        or os.getenv("RALFIA_ALERTS_EMAIL")
        or "rafagye@gmail.com"
    ).strip()
    return raw.split(",")[0].strip()


def notify_owner(
    *,
    title: str,
    body: str,
    kind: str = "summary",
    task_id: str | None = None,
    email_always: bool = True,
    ha: bool = True,
    telegram: bool = True,
) -> dict[str, Any]:
    """Deliver the same summary across configured channels (best-effort)."""
    out: dict[str, Any] = {"ok": False, "channels": {}, "kind": kind}
    title = (title or "InnerOS").strip()[:120]
    body = (body or "").strip()
    plain = body.replace("**", "").replace("#", "")[:12000]

    if telegram and os.getenv("NOTIFY_OPS_TELEGRAM", "1").strip().lower() not in {"0", "false", "no", "off"}:
        try:
            from inneros_core_runtime.notifications import ops_owner_delivery as mult

            tg_body = f"*{title}*\n\n{plain[:3500]}"
            r = mult.deliver_text_fanout(
                tg_body,
                kind=kind,
                dedupe_key=f"{kind}:{title[:40]}",
                inline_ops_task_id=task_id,
            )
            out["channels"]["telegram_fanout"] = r
            if r.get("ok"):
                out["ok"] = True
        except Exception as exc:
            out["channels"]["telegram"] = {"ok": False, "error": str(exc)[:200]}

    if ha and os.getenv("NOTIFY_OPS_AUTH_HA", "0").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from inneros_core_runtime.notifications import ops_ha_owner_auth as ops_ha

            ha_out = ops_ha.notify_companion_scout_alert(title=title, message=plain[:3500])
            out["channels"]["ha"] = ha_out
            if ha_out.get("ok"):
                out["ok"] = True
        except Exception as exc:
            out["channels"]["ha"] = {"ok": False, "error": str(exc)[:200]}

    if email_always:
        try:
            from inneros_core_runtime.notifications.email_client import send_email

            subject = f"{SUBJECT_PREFIX} {title}"[:180]
            mail = send_email(
                to_addr=owner_email(),
                subject=subject,
                body=plain,
                from_account=os.getenv("EMAIL_OPS_ACCOUNT_HINT", "rlopez@pcdoctor.com.ec"),
            )
            out["channels"]["email"] = mail
            if mail.get("ok"):
                out["ok"] = True
        except Exception as exc:
            out["channels"]["email"] = {"ok": False, "error": str(exc)[:200]}

    return out


def notify_owner_photo(
    *,
    caption: str,
    image_bytes: bytes,
    title: str = "Vigilancia",
    filename: str = "guardian.jpg",
    ha: bool = True,
    whatsapp_fallback: bool = True,
) -> dict[str, Any]:
    """Foto perimetral / Physical Guardian → Telegram primero, luego HA push y WhatsApp si está activo."""
    out: dict[str, Any] = {"ok": False, "channels": {}, "kind": "owner_photo"}
    cap = (caption or title or "Alerta").strip()[:900]
    title = (title or "Vigilancia").strip()[:120]
    if not image_bytes:
        return {**out, "error": "empty_image"}

    if os.getenv("NOTIFY_OPS_TELEGRAM", "1").strip().lower() not in {"0", "false", "no", "off"}:
        try:
            from inneros_core_runtime.notifications import telegram_client as tg

            tg_cap = f"*{title}*\n{cap}" if title else cap
            tg_r = tg.send_photo(image_bytes, caption=tg_cap[:1000], filename=filename)
            out["channels"]["telegram"] = tg_r
            if tg_r.get("ok"):
                out["ok"] = True
        except Exception as exc:
            out["channels"]["telegram"] = {"ok": False, "error": str(exc)[:200]}

    if ha and os.getenv("NOTIFY_OPS_AUTH_HA", "0").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from inneros_core_runtime.notifications import ops_ha_owner_auth as ops_ha

            ha_r = ops_ha.notify_companion_scout_alert(title=title, message=cap[:3500])
            out["channels"]["ha"] = ha_r
            if ha_r.get("ok"):
                out["ok"] = True
        except Exception as exc:
            out["channels"]["ha"] = {"ok": False, "error": str(exc)[:200]}

    if whatsapp_fallback and os.getenv("INNEROS_WHATSAPP_NOTIFICATIONS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        try:
            from inneros_core_runtime.notifications.evolution_client import send_alert_whatsapp_image

            wa_r = send_alert_whatsapp_image(cap, image_bytes)
            out["channels"]["whatsapp"] = wa_r
            if wa_r.get("ok"):
                out["ok"] = True
        except Exception as exc:
            out["channels"]["whatsapp"] = {"ok": False, "error": str(exc)[:200]}

    return out


def mirror_ops_alert(text: str, *, title: str = "RalfIA") -> dict[str, Any]:
    """Alertas operativas (ex-WhatsApp): HA + Telegram, sin duplicar email."""
    return notify_owner(
        title=title[:120],
        body=text,
        kind="ops_alert",
        email_always=False,
        ha=True,
        telegram=True,
    )
