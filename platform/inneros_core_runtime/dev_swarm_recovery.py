"""Recovery lane for blocked dev_swarm ops tasks with explicit retry."""

from __future__ import annotations

from typing import Any

from raphiia_openai import coordination_live, dev_swarm_scheduler

SAFE_INNEROS_REPO = dev_swarm_scheduler.SAFE_INNEROS_REPO


def scheduler_recovery_tick(
    limit: int = 6,
    dry_run: bool = False,
    task_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Re-admit blocked dev_swarm tasks that requested an explicit retry."""
    db = dev_swarm_scheduler._db()
    reconcile = dev_swarm_scheduler.reconcile_capacity_state(reason="recovery_lane")
    capacity = dev_swarm_scheduler.capacity_status()
    recommendation = capacity.get("recommendation") or {}
    admittable = int(recommendation.get("admittable_now") or 0)
    active = int((capacity.get("workers") or {}).get("active_worker_count") or 0)

    query: dict[str, Any] = {
        "owner": "dev_swarm",
        "status": {"$in": ["accepted", "in_progress", "blocked"]},
        "dev_swarm_retry_requested": True,
    }
    if task_ids:
        cleaned = [str(task_id).strip() for task_id in task_ids if str(task_id).strip()]
        if cleaned:
            query["task_id"] = {"$in": cleaned}

    scan_limit = max(1, min(int(limit or 6), 25))
    candidates = list(
        db[coordination_live.OPS_TASKS_COL]
        .find(query, {"_id": 0})
        .sort("updated_at", 1)
        .limit(scan_limit * 3)
    )
    candidates.sort(key=dev_swarm_scheduler._priority_key)

    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    now = dev_swarm_scheduler._now()

    for task in candidates:
        task_id = str(task.get("task_id") or "")
        if not task_id:
            continue
        if len(selected) >= admittable and not dry_run:
            skipped.append({"task_id": task_id, "reason": "capacity_budget_exhausted"})
            continue
        ok, reason, repo = dev_swarm_scheduler._eligible_reason(task)
        if not ok:
            skipped.append({"task_id": task_id, "reason": reason, "repo": repo})
            if not dry_run:
                db[coordination_live.OPS_TASKS_COL].update_one(
                    {"task_id": task_id},
                    {
                        "$set": {
                            "dev_swarm_last_skip_reason": reason,
                            "dev_swarm_last_skip_at": now,
                            "dev_swarm_last_skip_repo": repo,
                            "updated_at": now,
                        }
                    },
                )
            continue
        selected.append(
            {
                "task_id": task_id,
                "repo": repo or SAFE_INNEROS_REPO,
                "priority": task.get("priority"),
            }
        )
        if dry_run:
            continue
        db[coordination_live.OPS_TASKS_COL].update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "dev_swarm_recovery_at": now,
                    "dev_swarm_recovery_reason": "recovery_lane",
                    "updated_at": now,
                }
            },
        )

    payload: dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "lane": "scheduler_recovery",
        "reconcile": reconcile,
        "capacity": capacity,
        "admittable_now": admittable,
        "active_worker_count": active,
        "selected": selected,
        "skipped": skipped,
        "results": [],
    }

    if dry_run:
        return payload

    if admittable <= 0 or not selected:
        if admittable <= 0 and selected:
            payload["skipped"].extend(
                {"task_id": row["task_id"], "reason": "gpu_capacity_zero"} for row in selected
            )
            payload["selected"] = []
        return payload

    batches: dict[str, list[str]] = {}
    for row in selected[:admittable]:
        batches.setdefault(str(row.get("repo") or SAFE_INNEROS_REPO), []).append(str(row["task_id"]))

    results: list[dict[str, Any]] = []
    for repo, ids in batches.items():
        results.append(
            dev_swarm_scheduler.fanout_execute(
                repo=repo,
                task_ids=ids,
                concurrency=min(admittable, len(ids)),
                dry_run=False,
            )
        )
    payload["results"] = results
    payload["ok"] = all(result.get("ok") for result in results) if results else True
    return payload
