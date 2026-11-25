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

    from inneros_core_runtime import owner_push_history as inbox

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
        try:
            inbox.record_decision(task_id=task_id, decision=decision, channel=channel, ok=True)
        except Exception:
            pass
        return {"ok": True, "task_id": task_id, "decision": "cancel", "channel": channel}

    from inneros_core_runtime import execution_binding as eb
    from inneros_core_runtime import interactive_ops_orchestrator as ioo
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from raphiia_openai import mongo_store

    task_row = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or {}
    provider = eb.normalize_provider(task_row.get("assignee") or task_row.get("preferred_provider"))
    out = ioo.owner_order_execute(
        provider,
        task_id=task_id,
        owner_actor=owner_actor,
        channel=channel,
        owner_approved=True,
    )
    ok = bool(out.get("ok"))
    try:
        inbox.record_decision(task_id=task_id, decision=decision, channel=channel, ok=ok)
    except Exception:
        pass
    task_after = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or task_row
    try:
        from inneros_core_runtime.notifications import inneros_owner_lifecycle as life

        if ok:
            life.notify_lifecycle(task_after, event="claimed", detail="El agente tomó la tarea.", force=True)
        else:
            err = str(out.get("error") or (out.get("claim") or {}).get("error") or "claim_pendiente")
            life.notify_lifecycle(
                task_after,
                event="authorized_pending_claim",
                detail=f"Autorizada en InnerOS. Claim: {err}",
                force=True,
            )
    except Exception:
        pass
    return {
        "ok": True,
        "decision_applied": True,
        "authorize_ok": ok,
        "task_id": task_id,
        "decision": "approve",
        "channel": channel,
        "authorize": out,
        "message": "Tarea en curso." if ok else "Autorizada; el claim del IDE sigue pendiente en Intel.",
    }