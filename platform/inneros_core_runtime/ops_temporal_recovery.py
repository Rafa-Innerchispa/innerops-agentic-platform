"""Re-open Temporal execution when the canonical workflow is already terminal."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any

from raphiia_openai import mongo_store

from inneros_core_runtime.coordination_live import OPS_TASKS_COL, _publish_task_event
from inneros_core_runtime import durable_coordination_spine as spine


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_until(hours: int = 8) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def _describe_workflow(workflow_id: str) -> dict[str, Any]:
    try:
        from temporalio.client import Client
        import os

        client = await Client.connect(
            os.getenv("TEMPORAL_HOST", "127.0.0.1:7233"),
            namespace=os.getenv("INNEROS_TEMPORAL_NAMESPACE", "default"),
        )
        from temporalio.client import WorkflowExecutionStatus

        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        raw_status = desc.status
        if isinstance(raw_status, int):
            try:
                status_name = WorkflowExecutionStatus(raw_status).name
            except ValueError:
                status_name = str(raw_status)
        else:
            status_name = str(getattr(raw_status, "name", raw_status))
        terminal = status_name in {
            "COMPLETED",
            "FAILED",
            "TERMINATED",
            "CANCELED",
            "CANCELLED",
        } or any(x in status_name for x in ("COMPLETED", "FAILED", "TERMINATED", "CANCELED", "CANCELLED"))
        return {"ok": True, "workflow_id": workflow_id, "status": status_name, "terminal": terminal}
    except Exception as exc:
        return {"ok": False, "workflow_id": workflow_id, "error": type(exc).__name__, "detail": str(exc)[:240]}


def reopen_ops_temporal_execution(
    task_id: str,
    *,
    reason: str,
    actor: str = "inneros_temporal_recovery",
) -> dict[str, Any]:
    """Start a new workflow generation and re-handoff Cursor claim if present."""
    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}

    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": tid}

    canonical = f"ops_task:{tid}"
    current_wf = str(task.get("workflow_id") or canonical)
    described = asyncio.run(_describe_workflow(current_wf))
    if described.get("ok") and not described.get("terminal"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "workflow_still_active",
            "workflow_id": current_wf,
            "temporal": described,
        }

    gen = int(task.get("workflow_generation") or 0) + 1
    new_wf = f"{canonical}:g{gen}"
    envelope = {**task, "workflow_id": new_wf, "workflow_generation": gen, "temporal_reopen_reason": reason}

    started = spine.start_task_workflow(envelope)
    if not started.get("ok"):
        return {"ok": False, "error": "start_task_workflow_failed", "details": started, "task_id": tid}

    now = _now()
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$set": {
                "workflow_id": new_wf,
                "workflow_generation": gen,
                "temporal_run_id": started.get("run_id"),
                "temporal_reopened_at": now,
                "temporal_reopen_reason": reason,
                "updated_at": now,
                "lease_until": _lease_until(),
            },
            "$unset": {
                "headless_execution_started_at": "",
                "headless_execution_finished_at": "",
                "headless_execution_pid": "",
                "completion_submitted_at": "",
            },
            "$inc": {"revision": 1},
        },
    )

    handoff_payload: dict[str, Any] | None = None
    token = str(task.get("claim_token") or "").strip()
    if token:
        handoff_payload = {
            "claim_token": token,
            "status": str(task.get("status") or "claimed"),
            "claim_host": task.get("claim_host") or task.get("cursor_execution_host"),
            "worktree": task.get("worktree"),
            "preferred_model": task.get("effective_model") or task.get("preferred_model"),
            "effective_model": task.get("effective_model") or task.get("preferred_model"),
            "owner_approved": True,
            "owner_authorized_at": task.get("owner_authorized_at"),
            "reopened": True,
            "workflow_generation": gen,
        }
        signal = spine.signal_task_workflow(
            tid,
            "cursor_claim_handoff",
            handoff_payload,
            workflow_id=new_wf,
        )
    else:
        signal = {"ok": True, "skipped": "no_claim_token"}

    _publish_task_event(
        "coordination.checkpoint",
        {**task, "workflow_id": new_wf},
        actor=actor,
        status=str(task.get("status") or "in_progress"),
        payload={"reason": reason, "workflow_generation": gen, "temporal_start": started},
    )
    return {
        "ok": True,
        "task_id": tid,
        "workflow_id": new_wf,
        "workflow_generation": gen,
        "temporal_start": started,
        "cursor_claim_handoff": signal,
        "previous_workflow": described,
    }
