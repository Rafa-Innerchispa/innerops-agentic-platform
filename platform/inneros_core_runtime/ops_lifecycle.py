"""End-to-end ops lifecycle: completion fallback, ChatGPT handoff, terminal WhatsApp."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store, ralfia_time

TERMINAL = frozenset({"completed", "failed", "blocked", "partial", "cancelled", "superseded", "changes_required"})


def emit_chatgpt_completion_handoff(task: dict[str, Any], *, phase: str = "verification") -> dict[str, Any]:
    tid = str(task.get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    corr = str(task.get("correlation_id") or "")
    idempotency_key = f"TASK_COMPLETION_READY_FOR_REVIEW:{tid}:{phase}"
    from inneros_core_runtime import durable_coordination_spine as spine

    body = (
        f"TASK_COMPLETION_READY_FOR_REVIEW\n"
        f"task_id: {tid}\n"
        f"correlation_id: {corr}\n"
        f"status: {phase}\n"
        f"provider: {task.get('preferred_provider') or task.get('assignee')}\n"
        f"title: {str(task.get('title') or '')[:200]}\n"
        "Use list_ops_tasks / fetch ops evidence for full detail."
    )
    return spine.create_durable_message(
        task_id=tid,
        workflow_id=str(task.get("workflow_id") or f"ops_task:{tid}"),
        run_id=str(task.get("run_id") or ""),
        correlation_id=corr,
        sender=str(task.get("claimed_by") or task.get("assignee") or "inneros"),
        recipient="chatgpt",
        subject=f"[TASK_COMPLETION_READY_FOR_REVIEW] {tid}",
        content=body,
        metadata={"handoff": True, "phase": phase, "terminal": phase in TERMINAL},
        idempotency_key=idempotency_key,
    )


def emit_owner_terminal_whatsapp(task: dict[str, Any], *, previous_status: str = "") -> dict[str, Any]:
    status = str(task.get("status") or "").lower()
    if status not in TERMINAL:
        return {"ok": False, "skipped": f"not_terminal:{status}"}
    tid = str(task.get("task_id") or "")
    db = mongo_store.get_db()
    flag = f"owner_terminal_whatsapp:{tid}:{status}"
    notes = (db[OPS_TASKS_COL].find_one({"task_id": tid}, {"lifecycle_notifications": 1}) or {}).get("lifecycle_notifications") or []
    if not isinstance(notes, list):
        notes = []
    if flag in notes:
        return {"ok": True, "duplicate": True, "task_id": tid}
    from inneros_core_runtime.notifications.ops_task_alerts import notify_ops_transition

    out = notify_ops_transition(task, previous_status=previous_status, actor="lifecycle")
    if out.get("ok"):
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid},
            {"$addToSet": {"lifecycle_notifications": flag}},
        )
    return out


def finalize_verification_to_completed(task_id: str, *, actor: str = "chatgpt", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verification gate pass → completed + owner FIN notification + ChatGPT ack."""
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found"}
    prev = str(task.get("status") or "")
    if prev != "verification":
        return {"ok": False, "error": "not_in_verification", "status": prev}
    now = ralfia_time.now_utc_iso()
    db[OPS_TASKS_COL].update_one(
        {"task_id": task_id},
        {
            "$set": {
                "status": "completed",
                "completed_at": now,
                "updated_at": now,
                "verified_by": actor,
                "verified_evidence": evidence or {},
            },
            "$inc": {"revision": 1},
        },
    )
    task2 = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or task
    whatsapp = emit_owner_terminal_whatsapp({**task2, "status": "completed"}, previous_status="verification")
    return {"ok": True, "task_id": task_id, "status": "completed", "whatsapp": whatsapp}


def submit_completion_with_temporal_fallback(
    task_id: str,
    *,
    claim_token: str,
    status: str,
    evidence: dict[str, Any],
    agent_result: dict[str, Any],
    actor: str,
    signal_name: str,
) -> dict[str, Any]:
    """Signal Temporal; on failure persist pending replay and still advance to verification."""
    from inneros_core_runtime import durable_coordination_spine

    now = ralfia_time.now_utc_iso()
    payload = {
        "submitted": True,
        "status": status,
        "agent_result": agent_result,
        "evidence": evidence,
        "claim_token": claim_token,
        "actor": actor,
        "at": now,
    }
    temporal = durable_coordination_spine.signal_task_workflow(task_id, signal_name, payload)
    db = mongo_store.get_db()
    set_fields: dict[str, Any] = {
        "status": "verification",
        "executed_at": now,
        "updated_at": now,
        "completion_submitted_at": now,
        "candidate_evidence": evidence,
        "candidate_agent_result": agent_result,
    }
    if not temporal.get("ok"):
        set_fields["pending_temporal_completion"] = {
            "signal": signal_name,
            "payload": payload,
            "error": temporal.get("error"),
            "at": now,
        }
        set_fields["temporal_completion_sync"] = "pending"
    else:
        set_fields["temporal_completion_sync"] = "ok"
    db[OPS_TASKS_COL].update_one(
        {"task_id": task_id, "claim_token": claim_token},
        {"$set": set_fields, "$inc": {"revision": 1}},
    )
    task = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or {}
    handoff = emit_chatgpt_completion_handoff({**task, "status": "verification"}, phase="verification")
    ok = True  # Mongo advanced; Temporal may catch up via reconciler
    return {
        "ok": ok,
        "task_id": task_id,
        "status": "verification",
        "temporal": temporal,
        "chatgpt_handoff": handoff,
        "temporal_deferred": not temporal.get("ok"),
    }


def replay_pending_temporal_completion(task: dict[str, Any]) -> dict[str, Any]:
    pending = task.get("pending_temporal_completion")
    if not isinstance(pending, dict):
        return {"ok": False, "skipped": "no_pending"}
    tid = str(task.get("task_id") or "")
    from inneros_core_runtime import durable_coordination_spine

    temporal = durable_coordination_spine.signal_task_workflow(
        tid,
        str(pending.get("signal") or "cursor_execution_complete"),
        pending.get("payload") or {},
    )
    if temporal.get("ok"):
        mongo_store.get_db()[OPS_TASKS_COL].update_one(
            {"task_id": tid},
            {
                "$set": {"temporal_completion_sync": "ok", "updated_at": ralfia_time.now_utc_iso()},
                "$unset": {"pending_temporal_completion": ""},
            },
        )
    return {"ok": bool(temporal.get("ok")), "temporal": temporal, "task_id": tid}


# Live canary: never mutate while headless PID active (observation only).
_PROTECTED_CANARY_IDS = frozenset(
    {x.strip() for x in os.getenv("OPS_LIFECYCLE_PROTECTED_TASK_IDS", "ops_e23af9238701").split(",") if x.strip()}
)


def is_protected_live_canary(task_id: str) -> bool:
    return task_id in _PROTECTED_CANARY_IDS
