"""Push owner 100% InnerOS: ntfy en Intel + PWA. Sin HA/Telegram obligatorios."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.notifications import inneros_ntfy_client as ntfy
from inneros_core_runtime.notifications import ops_ha_owner_auth as ops_ha
from inneros_core_runtime.notifications import inneros_owner_message as msgfmt
from inneros_core_runtime.owner_push_tokens import public_base_url, sign_decision


def is_primary() -> bool:
    primary = (os.getenv("NOTIFY_OPS_PRIMARY") or "inneros_push").strip().lower()
    enabled = os.getenv("NOTIFY_OPS_INNEROS_PUSH", "1").strip().lower() in {"1", "true", "yes", "on"}
    return enabled and primary in {"inneros_push", "inneros", "ntfy"}


def ha_fallback_enabled() -> bool:
    return os.getenv("NOTIFY_OPS_AUTH_HA", "0").strip().lower() in {"1", "true", "yes", "on"}


def notify_ops_owner_authorization(
    task: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
    headline: str = "",
    body: str = "",
) -> dict[str, Any]:
    from inneros_core_runtime import ops_owner_decision_registry as decisions

    decision_out = decisions.publish_decision_request(task)
    if decision_out.get("duplicate"):
        from inneros_core_runtime import owner_push_history as _inbox

        tid_pre = str(task.get("task_id") or "")
        for row in _inbox.list_inbox(limit=5, kinds=["auth_request"]):
            if str(row.get("task_id") or "") == tid_pre and str(row.get("status") or "") == "pending":
                return {
                    "ok": True,
                    "channel": "inneros_push",
                    "skipped_duplicate_auth_push": True,
                    "decision_registry": decision_out,
                    "task_id": tid_pre,
                }
    if not decision_out.get("ok") and decision_out.get("error") != "decision_already_closed":
        return {"ok": False, "decision_registry": decision_out, "channel": "inneros_push"}
    tid = str(task.get("task_id") or "")
    nonce = str(decision_out.get("nonce") or "")
    if not nonce:
        return {"ok": False, "error": "missing_decision_nonce", "decision_registry": decision_out}
    pending = ops_ha.persist_pending(task, summary=summary, headline=headline, body=body)
    provider = str(task.get("assignee") or task.get("preferred_provider") or "?").upper()
    alias = msgfmt.task_code(task)
    title, message = msgfmt.format_owner_push(
        task,
        event="auth_request",
        headline=headline,
        detail=body or "Toca para autorizar o usa Aprobar / Cancelar.",
    )
    base = public_base_url()
    approve_t = sign_decision(task_id=tid, nonce=nonce, decision="approve")
    cancel_t = sign_decision(task_id=tid, nonce=nonce, decision="cancel")
    approve_url = f"{base}/owner-ops/decide?task_id={tid}&nonce={nonce}&decision=approve&token={approve_t}"
    cancel_url = f"{base}/owner-ops/decide?task_id={tid}&nonce={nonce}&decision=cancel&token={cancel_t}"
    detail_url = f"{base}/owner-ops/?task_id={tid}"
    from inneros_core_runtime import owner_push_history as inbox

    ntfy_out = ntfy.publish(
        message[:3800],
        title=title,
        tags=["warning", "rotating_light"],
        priority="high",
        click=detail_url,
        actions=[
            {"action": "http", "label": "Aprobar", "url": approve_url, "clear": True},
            {"action": "http", "label": "Cancelar", "url": cancel_url, "clear": True},
        ],
        extras={"task_id": tid, "nonce": nonce, "channel": "inneros_push"},
    )
    if ntfy_out.get("ok"):
        try:
            inbox.record_auth_push(
                task_id=tid,
                human_task_id=alias,
                provider=provider,
                title=title,
                message=message,
                nonce=nonce,
                ntfy_id=str(ntfy_out.get("id") or ""),
            )
        except Exception:
            pass
    ha_out: dict[str, Any] = {"ok": False, "skipped": "inneros_push_primary"}
    if ha_fallback_enabled():
        ha_out = ops_ha.notify_ops_owner_ha_authorization(task, summary=summary, headline=headline, body=body)
    tg_out: dict[str, Any] = {"ok": False, "skipped": "not_attempted"}
    if os.getenv("NOTIFY_OPS_TELEGRAM_MIRROR_ON_PUSH", "1").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from inneros_core_runtime import human_task_id as hti
            from inneros_core_runtime.notifications import telegram_client as tg

            if tg.telegram_enabled() and tg.configured():
                alert_kind = str((summary or {}).get("owner_whatsapp_alert_kind") or "external_spend")
                tg_body = hti.format_telegram_owner_body(
                    task=task,
                    headline=headline or f"🛂 {provider} · autorizar OPS",
                    provider=provider,
                    objective=str(task.get("objective") or task.get("title") or "")[:400],
                    spends="Toca Aprobar en Telegram o abre el enlace InnerOS.",
                    detail=(body or "")[:600],
                    alert_kind=alert_kind,
                    short_ops_suffix=tid.replace("ops_", "")[:6],
                    related=[],
                )
                tg_out = tg.send_message(
                    tg_body,
                    reply_markup=tg.ops_auth_inline_keyboard(tid),
                    parse_mode="Markdown",
                )
        except Exception as exc:
            tg_out = {"ok": False, "error": str(exc)[:200]}
    ok = bool(ntfy_out.get("ok") or ha_out.get("ok") or tg_out.get("ok"))
    modes = []
    if ntfy_out.get("ok"):
        modes.append("inneros_ntfy")
    if ha_out.get("ok"):
        modes.append("ha_companion_ops")
    if tg_out.get("ok"):
        modes.append("telegram")
    if decision_out.get("ok"):
        modes.append("alexa_shared_registry")
    return {
        "ok": ok,
        "channel": "inneros_push",
        "ntfy": ntfy_out,
        "ha_companion": ha_out,
        "telegram": tg_out,
        "decision_registry": decision_out,
        "task_id": tid,
        "delivery_mode": "+".join(modes) if modes else "unreachable",
        "approve_url": approve_url,
        "pwa_url": detail_url,
    }