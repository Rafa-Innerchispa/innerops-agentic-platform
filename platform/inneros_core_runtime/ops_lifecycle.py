"""End-to-end ops lifecycle: completion fallback, ChatGPT handoff, terminal WhatsApp."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store, ralfia_time

TERMINAL = frozenset({"completed", "failed", "blocked", "partial", "cancelled", "superseded", "changes_required"})
EXECUTION_FAILURE = frozenset({"blocked", "failed", "partial", "changes_required"})


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
    msg = spine.create_durable_message(
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
    try:
        from inneros_core_runtime import ops_coordination_broadcast as ocb

        phase_name = "completed" if str(phase).lower() in TERMINAL else "delivered_for_review"
        ocb.fanout_ops_phase(task, phase=phase_name, actor=str(task.get("assignee") or "inneros"))
    except Exception:
        pass
    return msg


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
    """Verification gate pass → COMPLETED_VERIFIED + owner FIN notification (CAS, fail-closed)."""
    from inneros_core_runtime import ops_global_completion_gate as ogcg
    from inneros_core_runtime import racb_protocol as racb

    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found"}
    prev = str(task.get("status") or "")
    if prev != "verification":
        return {"ok": False, "error": "not_in_verification", "status": prev}

    merged_evidence = dict(evidence or {})
    candidate = task.get("candidate_evidence") if isinstance(task.get("candidate_evidence"), dict) else {}
    merged_evidence = {**candidate, **merged_evidence}
    gate = ogcg.evaluate_global_completion(task, merged_evidence)
    if not gate.get("ok"):
        return {
            "ok": False,
            "error": "global_completion_gate_failed",
            "task_id": task_id,
            "certification": gate.get("certification"),
            "reasons": gate.get("reasons"),
            "gate": gate,
        }

    receipt = gate.get("receipt") or {}
    terminal_evidence = {
        **merged_evidence,
        "status": "COMPLETED_VERIFIED",
        "result": "COMPLETED_VERIFIED",
        "global_completion_ack": True,
        "verified_receipt": receipt,
    }
    transition = racb.build_transition(
        current_status=prev,
        target_status="completed",
        actor=actor,
        current_revision=int(task.get("revision") or 0),
        evidence=terminal_evidence,
        force_handoff=True,
    )
    if not transition.get("ok"):
        return {"ok": False, "error": transition.get("error"), "task_id": task_id, "transition": transition}

    patch = dict(transition.get("patch") or {})
    patch.update(
        {
            "verified_by": actor,
            "verified_evidence": merged_evidence,
            "completion_certification": "COMPLETED_VERIFIED",
            "verified_receipt": receipt,
        }
    )
    filt: dict[str, Any] = {"task_id": task_id, "status": "verification"}
    if task.get("revision") is not None:
        filt["revision"] = task["revision"]
    change = db[OPS_TASKS_COL].update_one(filt, {"$set": patch})
    if getattr(change, "modified_count", 0) != 1:
        return {"ok": False, "error": "concurrent_completion_race", "task_id": task_id}

    task2 = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or task
    whatsapp = emit_owner_terminal_whatsapp({**task2, "status": "completed"}, previous_status="verification")
    return {
        "ok": True,
        "task_id": task_id,
        "status": "completed",
        "certification": "COMPLETED_VERIFIED",
        "receipt": receipt,
        "whatsapp": whatsapp,
    }


def _candidate_evidence_indicates_failure(evidence: dict[str, Any], agent_result: dict[str, Any]) -> bool:
    if agent_result.get("blocked") or agent_result.get("failed"):
        return True
    tests = evidence.get("test_results") if isinstance(evidence.get("test_results"), dict) else {}
    if tests.get("ok") is False:
        return True
    exit_code = tests.get("exit_code")
    if exit_code is not None and int(exit_code) != 0:
        return True
    notes = str(evidence.get("notes") or "").lower()
    if any(marker in notes for marker in ("bounded_run_failed", "blocked_reason", "worktree path does not exist")):
        return True
    return False


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
    """Signal Temporal; completed → verification gate; failures → terminal Mongo status (fail-closed)."""
    from inneros_core_runtime import durable_coordination_spine

    normalized = (status or "completed").strip().lower()
    now = ralfia_time.now_utc_iso()
    payload = {
        "submitted": True,
        "status": normalized,
        "agent_result": agent_result,
        "evidence": evidence,
        "claim_token": claim_token,
        "actor": actor,
        "at": now,
    }
    temporal = durable_coordination_spine.signal_task_workflow(task_id, signal_name, payload)
    db = mongo_store.get_db()
    task_before = db[OPS_TASKS_COL].find_one({"task_id": task_id, "claim_token": claim_token}, {"_id": 0}) or {}
    previous_status = str(task_before.get("status") or "in_progress")

    if normalized in EXECUTION_FAILURE or (
        normalized == "completed" and _candidate_evidence_indicates_failure(evidence, agent_result)
    ):
        terminal = normalized if normalized in EXECUTION_FAILURE else "blocked"
        from inneros_core_runtime import racb_protocol as racb

        transition = racb.build_transition(
            current_status=previous_status,
            target_status=terminal,
            actor=actor,
            current_revision=int(task_before.get("revision") or 0),
            evidence=evidence,
            allow_legacy_direct=True,
        )
        patch: dict[str, Any]
        if transition.get("ok"):
            patch = dict(transition.get("patch") or {})
            inc_rev = False
        else:
            patch = {"status": terminal, "updated_at": now, "updated_by": actor}
            inc_rev = True
        patch.update(
            {
                "executed_at": now,
                "updated_at": now,
                "completion_submitted_at": now,
                "candidate_evidence": evidence,
                "candidate_agent_result": agent_result,
                "execution_outcome_requested": normalized,
            }
        )
        if not temporal.get("ok"):
            patch["pending_temporal_completion"] = {
                "signal": signal_name,
                "payload": payload,
                "error": temporal.get("error"),
                "at": now,
            }
            patch["temporal_completion_sync"] = "pending"
        else:
            patch["temporal_completion_sync"] = "ok"
        update: dict[str, Any] = {"$set": patch}
        if inc_rev:
            update["$inc"] = {"revision": 1}
        db[OPS_TASKS_COL].update_one({"task_id": task_id, "claim_token": claim_token}, update)
        task = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or {}
        handoff = emit_chatgpt_completion_handoff({**task, "status": terminal}, phase=terminal)
        emit_owner_terminal_whatsapp(task, previous_status=previous_status)
        return {
            "ok": True,
            "task_id": task_id,
            "status": terminal,
            "temporal": temporal,
            "chatgpt_handoff": handoff,
            "temporal_deferred": not temporal.get("ok"),
            "coerced_from": normalized if terminal != normalized else None,
        }

    mongo_status = "verification" if normalized == "completed" else normalized
    set_fields: dict[str, Any] = {
        "status": mongo_status,
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
    handoff = emit_chatgpt_completion_handoff({**task, "status": mongo_status}, phase=mongo_status)
    return {
        "ok": True,
        "task_id": task_id,
        "status": mongo_status,
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
