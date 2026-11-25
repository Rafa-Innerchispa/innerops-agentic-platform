"""Push owner 100% InnerOS: ntfy en Intel + PWA. Sin HA/Telegram obligatorios."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.notifications import inneros_ntfy_client as ntfy
from inneros_core_runtime.notifications import ops_ha_owner_auth as ops_ha
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
    if not decision_out.get("ok") and decision_out.get("error") != "decision_already_closed":
        return {"ok": False, "decision_registry": decision_out, "channel": "inneros_push"}
    tid = str(task.get("task_id") or "")
    nonce = str(decision_out.get("nonce") or "")
    if not nonce:
        return {"ok": False, "error": "missing_decision_nonce", "decision_registry": decision_out}
    pending = ops_ha.persist_pending(task, summary=summary, headline=headline, body=body)
    provider = str(task.get("assignee") or task.get("preferred_provider") or "?").upper()
    alias = str(task.get("human_task_id") or task.get("task_alias") or tid)
    title = (headline or f"{provider} · autorizar OPS")[:120]
    message = f"{alias}\n{provider}: toca para autorizar o usa botones Aprobar/Cancelar."
    base = public_base_url()
    approve_t = sign_decision(task_id=tid, nonce=nonce, decision="approve")
    cancel_t = sign_decision(task_id=tid, nonce=nonce, decision="cancel")
    approve_url = f"{base}/owner-ops/decide?task_id={tid}&nonce={nonce}&decision=approve&token={approve_t}"
    cancel_url = f"{base}/owner-ops/decide?task_id={tid}&nonce={nonce}&decision=cancel&token={cancel_t}"
    detail_url = f"{base}/owner-ops/?task_id={tid}"
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
    ha_out: dict[str, Any] = {"ok": False, "skipped": "inneros_push_primary"}
    if ha_fallback_enabled():
        ha_out = ops_ha.notify_ops_owner_ha_authorization(task, summary=summary, headline=headline, body=body)
    ok = bool(ntfy_out.get("ok") or ha_out.get("ok"))
    modes = []
    if ntfy_out.get("ok"):
        modes.append("inneros_ntfy")
    if ha_out.get("ok"):
        modes.append("ha_companion_ops")
    if decision_out.get("ok"):
        modes.append("alexa_shared_registry")
    return {
        "ok": ok,
        "channel": "inneros_push",
        "ntfy": ntfy_out,
        "ha_companion": ha_out,
        "decision_registry": decision_out,
        "task_id": tid,
        "delivery_mode": "+".join(modes) if modes else "unreachable",
        "approve_url": approve_url,
        "pwa_url": detail_url,
    }