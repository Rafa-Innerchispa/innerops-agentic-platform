"""Detect Dev Swarm launch success without scheduler worker admission."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

from raphiia_openai import coordination_live, mongo_store

WORKERS_COL = "ralfia_dev_swarm_workers"
OPS_COL = coordination_live.OPS_TASKS_COL

LOCAL_DEV_SWARM_LANE = "local_dev_swarm"
DISPATCH_PENDING_STATUSES = frozenset(
    {"running", "worker_starting", "dispatched", "accepted", "in_progress"}
)
HYDRATING_PHASES = frozenset(
    {"hydrating", "worktree_hydration", "launch_pending_worker", "dispatched"}
)

LAUNCH_DISPATCH_STALL_SECONDS = int(os.getenv("DEV_SWARM_LAUNCH_DISPATCH_STALL_SECONDS", "120"))
MAX_DISPATCH_REQUEUE_ATTEMPTS = int(os.getenv("DEV_SWARM_DISPATCH_REQUEUE_ATTEMPTS", "1"))


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def is_dev_swarm_managed_task(task: dict[str, Any]) -> bool:
    lane = str(task.get("execution_lane") or "").strip().lower()
    assignee = str(task.get("assignee") or "").strip().lower()
    owner = str(task.get("owner") or "").strip().lower()
    if lane in {LOCAL_DEV_SWARM_LANE, "dev_swarm", "internal"}:
        return True
    if assignee == "dev_swarm":
        return True
    if owner == "dev_swarm" and task.get("dev_swarm_retry_requested"):
        return True
    return False


def _task_evidence_phase(task: dict[str, Any]) -> str:
    evidence = task.get("evidence")
    if isinstance(evidence, dict):
        return str(evidence.get("phase") or "").strip().lower()
    return ""


def launch_dispatch_pending(task: dict[str, Any]) -> bool:
    if not is_dev_swarm_managed_task(task):
        return False
    if task.get("dev_swarm_retry_requested"):
        return True
    if task.get("dev_swarm_last_binding_ok"):
        return True
    phase = _task_evidence_phase(task)
    return phase in HYDRATING_PHASES


def has_active_dev_swarm_worker(db: Any, task_id: str, *, workers_col: str = WORKERS_COL) -> bool:
    if not task_id:
        return False
    query = {
        "task_id": task_id,
        "status": {"$in": ["starting", "running"]},
        "$or": [
            {"executor.status": {"$exists": False}},
            {"executor.status": {"$nin": ["executed", "needs_implementation", "failed", "blocked"]}},
        ],
    }
    return bool(db[workers_col].find_one(query, {"_id": 1}))


def dispatch_anchor_time(task: dict[str, Any]) -> datetime | None:
    for key in (
        "dev_swarm_last_binding_at",
        "dev_swarm_launch_pending_at",
        "updated_at",
        "created_at",
    ):
        parsed = _parse_dt(task.get(key))
        if parsed:
            return parsed
    return None


def _notify_owner_once(task: dict[str, Any], *, previous_status: str, blocker: str) -> None:
    try:
        from inneros_core_runtime import ops_lifecycle

        enriched = {**task, "blocker": blocker}
        ops_lifecycle.emit_owner_terminal_whatsapp(enriched, previous_status=previous_status)
    except Exception:
        pass


def reconcile_launch_dispatch_gaps(
    db: Any | None = None,
    *,
    now: datetime | None = None,
    now_iso: str = "",
    reason: str = "scheduler_tick",
    workers_col: str = WORKERS_COL,
    publish_event: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Requeue or fail Dev Swarm tasks that look active but have no worker."""
    db = db or mongo_store.get_db()
    now_dt = now or datetime.now(timezone.utc)
    now_iso = now_iso or now_dt.isoformat()
    stall_before = now_dt.timestamp() - LAUNCH_DISPATCH_STALL_SECONDS

    try:
        from inneros_core_runtime import coordination_liveness
    except Exception:
        coordination_liveness = None  # type: ignore[assignment]

    requeued = 0
    failed = 0
    actions: list[dict[str, Any]] = []

    rows = db[OPS_COL].find(
        {
            "status": {"$in": sorted(DISPATCH_PENDING_STATUSES)},
            "$or": [
                {"assignee": "dev_swarm"},
                {"owner": "dev_swarm"},
                {"execution_lane": LOCAL_DEV_SWARM_LANE},
                {"dev_swarm_retry_requested": True},
            ],
        },
        {"_id": 0},
    ).limit(200)

    for task in rows:
        task_id = str(task.get("task_id") or "")
        if not task_id or not launch_dispatch_pending(task):
            continue
        if coordination_liveness and coordination_liveness.is_external_managed_claim(task):
            continue
        if has_active_dev_swarm_worker(db, task_id, workers_col=workers_col):
            continue

        anchor = dispatch_anchor_time(task)
        if not anchor or anchor.timestamp() >= stall_before:
            continue

        previous_status = str(task.get("status") or "")
        attempts = int(task.get("dev_swarm_dispatch_requeue_count") or 0)

        if attempts < MAX_DISPATCH_REQUEUE_ATTEMPTS:
            patch = {
                "status": "proposed",
                "blocker": None,
                "dev_swarm_retry_requested": True,
                "dev_swarm_last_skip_reason": "scheduler_dispatch_requeue",
                "dev_swarm_last_skip_at": now_iso,
                "dev_swarm_dispatch_requeue_count": attempts + 1,
                "dev_swarm_launch_pending_at": now_iso,
                "updated_at": now_iso,
                "updated_by": "dev_swarm_dispatch_reconcile",
            }
            db[OPS_COL].update_one(
                {"task_id": task_id, "status": {"$in": sorted(DISPATCH_PENDING_STATUSES)}},
                {
                    "$set": patch,
                    "$push": {
                        "state_history": {
                            "from": previous_status,
                            "to": "proposed",
                            "actor": "dev_swarm_dispatch_reconcile",
                            "at": now_iso,
                            "reason": "scheduler_dispatch_requeue",
                            "reconcile_reason": reason,
                        }
                    },
                },
            )
            requeued += 1
            actions.append({"task_id": task_id, "action": "requeue_proposed", "previous_status": previous_status})
            if publish_event:
                publish_event(
                    "task.requeued",
                    task=task,
                    task_id=task_id,
                    repo=str(task.get("repo") or task.get("related_project") or ""),
                    status="proposed",
                    payload={"reason": "scheduler_dispatch_requeue", "reconcile_reason": reason},
                )
            continue

        blocker = "worker_not_started"
        if task.get("dev_swarm_last_binding_ok") and not task.get("dev_swarm_retry_requested"):
            blocker = "scheduler_dispatch_missed"
        patch = {
            "status": "blocked",
            "blocker": blocker,
            "dev_swarm_retry_requested": False,
            "dev_swarm_last_skip_reason": blocker,
            "dev_swarm_last_skip_at": now_iso,
            "dev_swarm_dispatch_failed_at": now_iso,
            "updated_at": now_iso,
            "updated_by": "dev_swarm_dispatch_reconcile",
        }
        db[OPS_COL].update_one(
            {"task_id": task_id, "status": {"$in": sorted(DISPATCH_PENDING_STATUSES)}},
            {
                "$set": patch,
                "$push": {
                    "state_history": {
                        "from": previous_status,
                        "to": "blocked",
                        "actor": "dev_swarm_dispatch_reconcile",
                        "at": now_iso,
                        "reason": blocker,
                        "reconcile_reason": reason,
                    }
                },
            },
        )
        failed += 1
        actions.append({"task_id": task_id, "action": "blocked", "blocker": blocker, "previous_status": previous_status})
        task_after = {**task, **patch}
        _notify_owner_once(task_after, previous_status=previous_status, blocker=blocker)
        if publish_event:
            publish_event(
                "task.blocked",
                task=task_after,
                task_id=task_id,
                repo=str(task.get("repo") or task.get("related_project") or ""),
                status="blocked",
                payload={"reason": blocker, "previous_status": previous_status, "reconcile_reason": reason},
            )

    return {
        "ok": True,
        "reason": reason,
        "stall_seconds": LAUNCH_DISPATCH_STALL_SECONDS,
        "requeued": requeued,
        "failed": failed,
        "actions": actions[:50],
    }
