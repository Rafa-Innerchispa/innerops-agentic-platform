"""Automatic recovery for stuck ops lifecycle (process, completion, notifications)."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime import ops_execution_state as oes
from inneros_core_runtime import ops_lifecycle as ol
from raphiia_openai import mongo_store, ralfia_time


def reconcile_ops_lifecycle(*, limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    out: dict[str, Any] = {"ok": True, "actions": []}

    # F: stale binding projection
    for task in db[OPS_TASKS_COL].find(
        {"status": {"$in": ["in_progress", "claimed", "verification", "completed"]}},
        {"_id": 0},
    ).sort("updated_at", -1).limit(limit):
        tid = str(task.get("task_id") or "")
        if ol.is_protected_live_canary(tid) and str(task.get("status")) == "in_progress":
            pid = task.get("headless_pid") or (task.get("headless_last_result") or {}).get("pid")
            if pid:
                continue
        eb = (task.get("evidence") or {}).get("execution_binding") or {}
        cur = task.get("current_execution_state") or {}
        if eb and not cur:
            oes.refresh_current_execution_state(task, event="reconcile_projection", actor="lifecycle_reconciler")
            out["actions"].append({"task_id": tid, "action": "refresh_execution_state"})

    # C: pending temporal completion replay
    for task in db[OPS_TASKS_COL].find(
        {"pending_temporal_completion": {"$exists": True}},
        {"_id": 0},
    ).limit(limit):
        tid = str(task.get("task_id") or "")
        if ol.is_protected_live_canary(tid):
            continue
        rep = ol.replay_pending_temporal_completion(task)
        out["actions"].append({"task_id": tid, "action": "replay_temporal", **rep})

    # D/E: terminal missing WhatsApp or ChatGPT handoff
    for task in db[OPS_TASKS_COL].find(
        {"status": {"$in": list(ol.TERMINAL)}},
        {"_id": 0},
    ).sort("updated_at", -1).limit(limit):
        tid = str(task.get("task_id") or "")
        notes = task.get("lifecycle_notifications") or []
        if task.get("status") == "completed" and f"owner_terminal_whatsapp:{tid}:completed" not in notes:
            ol.emit_owner_terminal_whatsapp(task, previous_status="verification")
            out["actions"].append({"task_id": tid, "action": "emit_terminal_whatsapp"})
        if task.get("status") in {"verification", "completed"}:
            key = f"TASK_COMPLETION_READY_FOR_REVIEW:{tid}:verification"
            exists = db["ralfia_agent_messages"].find_one({"idempotency_key": key}, {"_id": 1})
            if not exists and not ol.is_protected_live_canary(tid):
                ol.emit_chatgpt_completion_handoff(task, phase=str(task.get("status")))
                out["actions"].append({"task_id": tid, "action": "emit_chatgpt_handoff"})

    # A: headless finished but still in_progress
    for task in db[OPS_TASKS_COL].find(
        {"status": "in_progress", "headless_execution_finished_at": {"$exists": True}},
        {"_id": 0},
    ).sort("updated_at", -1).limit(limit):
        tid = str(task.get("task_id") or "")
        if ol.is_protected_live_canary(tid):
            continue
        hl = task.get("headless_last_result") or {}
        if hl.get("completion_submitted") is False and task.get("pending_temporal_completion"):
            ol.replay_pending_temporal_completion(task)
            out["actions"].append({"task_id": tid, "action": "recover_stuck_in_progress"})

    out["at"] = ralfia_time.now_utc_iso()
    return out
