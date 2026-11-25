"""Aprobación owner vía push InnerOS (sin Home Assistant)."""

from __future__ import annotations

from typing import Any

from inneros_core_runtime.owner_push_tokens import verify_decision


def apply_owner_push_decision(
    *,
    task_id: str,
    nonce: str,
    decision: str,
    token: str,
    owner_actor: str = "RAFAEL",
    channel: str = "inneros_push",
) -> dict[str, Any]:
    if decision not in {"approve", "cancel"}:
        return {"ok": False, "error": "invalid_decision"}
    if not verify_decision(task_id=task_id, nonce=nonce, decision=decision, token=token):
        return {"ok": False, "error": "invalid_token"}
    from inneros_core_runtime import ops_owner_decision_registry as decisions

    if decision == "approve":
        consumed = decisions.consume_decision(
            task_id=task_id, nonce=nonce, decision="approve", channel=channel, owner_actor=owner_actor,
        )
        if not consumed.get("ok"):
            return {
                "ok": False,
                "error": consumed.get("error") or "decision_rejected",
                "decided_by": consumed.get("decided_by"),
            }
    else:
        consumed = decisions.consume_decision(
            task_id=task_id, nonce=nonce, decision="cancel", channel=channel, owner_actor=owner_actor,
        )
        if not consumed.get("ok"):
            return {"ok": False, "error": consumed.get("error") or "decision_rejected"}
        from inneros_core_runtime import durable_coordination_spine

        durable_coordination_spine.signal_task_workflow(task_id, "cancel", "owner_rejected_push")
        return {"ok": True, "task_id": task_id, "decision": "cancel", "channel": channel}

    from inneros_core_runtime import ops_whatsapp_owner as shared_executor

    short = task_id.replace("ops_", "")[:6]
    out = shared_executor.handle_owner_reply(f"SI {short}", owner_actor=owner_actor, phone=None)
    return {"ok": bool(out and out.get("ok")), "task_id": task_id, "decision": "approve", "channel": channel, "authorize": out}