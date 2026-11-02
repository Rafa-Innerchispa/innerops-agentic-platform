"""Owner notifications: HA (P1) + email rafagye@gmail.com (P2) + Telegram (P3)."""

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

    return out
