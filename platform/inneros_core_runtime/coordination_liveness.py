"""Authoritative Coordination Liveness Supervisor for InnerOS Agentic Platform.

Manages authoritative task leases, detects frozen tasks / retry storms,
enforces retry budgets with failure signatures, releases orphan locks,
and provides per-tick reconciliation across AntiGravity, Cursor, Codex, and Dev Swarm.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store, racb_locks

OPS_TASKS_COL = "ralfia_ops_tasks"
LOCKS_COL = "ralfia_coordination_locks"
WORKERS_COL = "ralfia_dev_swarm_workers"
ANOMALIES_COL = "ralfia_dev_swarm_anomalies"

DEFAULT_LEASE_SECONDS = 600       # 10 minutes
DEFAULT_RETRY_BUDGET = 3          # Max 3 attempts for same failure signature
FROZEN_HEARTBEAT_THRESHOLD = 3    # 3 heartbeats without progress fingerprint change = frozen
COOLDOWN_SECONDS = 900            # 15 minutes cooldown on retry exhausted


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _parse_iso(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def compute_progress_fingerprint(
    *,
    files_touched: list[str] | None = None,
    tests_passed: list[str] | int | None = None,
    git_commit: str | None = None,
    evidence_summary: str | None = None,
) -> str:
    """Generate a deterministic fingerprint representing actual forward progress."""
    payload = {
        "files": sorted(set(str(f).strip() for f in (files_touched or []) if str(f).strip())),
        "tests": tests_passed,
        "commit": (git_commit or "").strip(),
        "summary": (evidence_summary or "").strip()[:500],
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_failure_signature(
    *,
    blocker_class: str | None = None,
    blocker_message: str | None = None,
    error_code: str | None = None,
) -> str:
    """Generate a stable signature for an error to detect identical retry storms."""
    payload = {
        "class": (blocker_class or "").strip().lower(),
        "msg": (blocker_message or "").strip().lower()[:200],
        "code": (error_code or "").strip().lower(),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def acquire_task_lease(
    task_id: str,
    worker_id: str,
    actor: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    retry_budget: int = DEFAULT_RETRY_BUDGET,
    repo: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically lease a task to an agent/worker and acquire repo lock if applicable."""
    db = mongo_store.get_db()
    now_dt = now or _now()
    now_str = _iso(now_dt)
    actor_n = (actor or "").strip().lower()
    worker_n = (worker_id or "").strip()
    task_n = (task_id or "").strip()

    if not task_n or not worker_n or not actor_n:
        return {"ok": False, "error": "missing_required_lease_fields"}

    task = db[OPS_TASKS_COL].find_one({"task_id": task_n}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": task_n}

    status = str(task.get("status") or "").lower()
    current_worker = str(task.get("worker_id") or "")
    lease_expires = _parse_iso(task.get("lease_expires_at"))

    # Active lease check
    if status == "in_progress" and current_worker and current_worker != worker_n:
        if lease_expires and lease_expires > now_dt:
            return {
                "ok": False,
                "error": "task_already_leased",
                "task_id": task_n,
                "worker_id": current_worker,
                "lease_expires_at": task.get("lease_expires_at"),
            }

    # Lock acquisition if repo is specified
    repo_resource = (repo or task.get("repo") or "").strip()
    lock_res = None
    if repo_resource:
        lock_res = racb_locks.manage_coordination_lock(
            action="acquire",
            resource_id=repo_resource,
            agent=actor_n,
            task_id=task_n,
            ttl_seconds=lease_seconds,
            force=False,
        )
        if not lock_res.get("ok") and not lock_res.get("idempotent_owner"):
            return {
                "ok": False,
                "error": "repo_lock_conflict",
                "repo": repo_resource,
                "lock_error": lock_res,
            }

    attempt_count = int(task.get("attempt_count") or 0) + 1
    expires_at_dt = now_dt + timedelta(seconds=max(30, lease_seconds))
    expires_at_str = _iso(expires_at_dt)

    patch = {
        "status": "in_progress",
        "owner": actor_n,
        "assignee": task.get("assignee") or actor_n,
        "worker_id": worker_n,
        "lease_acquired_at": now_str,
        "lease_expires_at": expires_at_str,
        "last_heartbeat_at": now_str,
        "last_progress_at": now_str,
        "attempt_count": attempt_count,
        "retry_budget": max(1, retry_budget),
        "no_progress_heartbeat_count": 0,
        "is_frozen": False,
        "updated_at": now_str,
        "updated_by": actor_n,
    }

    db[OPS_TASKS_COL].update_one({"task_id": task_n}, {"$set": patch})
    return {
        "ok": True,
        "action": "acquired",
        "task_id": task_n,
        "worker_id": worker_n,
        "lease_expires_at": expires_at_str,
        "attempt_count": attempt_count,
        "repo_lock": lock_res,
    }


def renew_task_lease(
    task_id: str,
    worker_id: str,
    actor: str,
    *,
    files_touched: list[str] | None = None,
    tests_passed: list[str] | int | None = None,
    git_commit: str | None = None,
    evidence_summary: str | None = None,
    next_action: str | None = None,
    blocker: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Renew lease and record forward progress or flag frozen state."""
    db = mongo_store.get_db()
    now_dt = now or _now()
    now_str = _iso(now_dt)
    actor_n = (actor or "").strip().lower()
    worker_n = (worker_id or "").strip()
    task_n = (task_id or "").strip()

    task = db[OPS_TASKS_COL].find_one({"task_id": task_n}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found"}

    if task.get("worker_id") != worker_n and task.get("owner") != actor_n:
        return {"ok": False, "error": "worker_mismatch", "current_worker": task.get("worker_id")}

    current_fp = task.get("progress_fingerprint") or ""
    new_fp = compute_progress_fingerprint(
        files_touched=files_touched,
        tests_passed=tests_passed,
        git_commit=git_commit,
        evidence_summary=evidence_summary,
    )

    has_progress = bool(new_fp != current_fp and (files_touched or tests_passed or git_commit or evidence_summary))
    no_prog_count = 0 if has_progress else (int(task.get("no_progress_heartbeat_count") or 0) + 1)
    is_frozen = no_prog_count >= FROZEN_HEARTBEAT_THRESHOLD

    expires_at_dt = now_dt + timedelta(seconds=max(30, lease_seconds))
    expires_at_str = _iso(expires_at_dt)

    patch: dict[str, Any] = {
        "lease_expires_at": expires_at_str,
        "last_heartbeat_at": now_str,
        "no_progress_heartbeat_count": no_prog_count,
        "is_frozen": is_frozen,
        "updated_at": now_str,
        "updated_by": actor_n,
    }

    if has_progress:
        patch["last_progress_at"] = now_str
        patch["progress_fingerprint"] = new_fp
    if next_action is not None:
        patch["next_action"] = str(next_action).strip() or None
    if blocker is not None:
        patch["blocker"] = str(blocker).strip() or None
    if files_touched is not None:
        patch["files_touched"] = [str(f).strip() for f in files_touched if str(f).strip()]

    # Renew repo lock
    repo_resource = str(task.get("repo") or "").strip()
    if repo_resource:
        racb_locks.manage_coordination_lock(
            action="renew",
            resource_id=repo_resource,
            agent=actor_n,
            task_id=task_n,
            ttl_seconds=lease_seconds,
        )

    db[OPS_TASKS_COL].update_one({"task_id": task_n}, {"$set": patch})
    return {
        "ok": True,
        "task_id": task_n,
        "worker_id": worker_n,
        "lease_expires_at": expires_at_str,
        "has_progress": has_progress,
        "is_frozen": is_frozen,
        "no_progress_heartbeat_count": no_prog_count,
    }


def release_task_lease(
    task_id: str,
    worker_id: str,
    actor: str,
    *,
    terminal_status: str = "completed",
    reason: str | None = None,
    evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Release lease and associated repo locks."""
    db = mongo_store.get_db()
    now_dt = now or _now()
    now_str = _iso(now_dt)
    actor_n = (actor or "").strip().lower()
    task_n = (task_id or "").strip()

    task = db[OPS_TASKS_COL].find_one({"task_id": task_n}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found"}

    # Release repo lock
    repo_resource = str(task.get("repo") or "").strip()
    if repo_resource:
        racb_locks.manage_coordination_lock(
            action="release",
            resource_id=repo_resource,
            agent=actor_n,
            task_id=task_n,
            force=True,
        )

    patch: dict[str, Any] = {
        "lease_expires_at": now_str,
        "updated_at": now_str,
        "updated_by": actor_n,
    }
    if terminal_status:
        patch["status"] = terminal_status
    if evidence:
        patch["evidence"] = evidence
    if reason:
        patch["release_reason"] = reason

    db[OPS_TASKS_COL].update_one({"task_id": task_n}, {"$set": patch})
    return {"ok": True, "task_id": task_n, "status": terminal_status, "released_at": now_str}


def reconcile_coordination_liveness(
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Per-tick reconciler: releases expired leases, breaks frozen retry storms,
    reclaims orphan locks, and auto-cleans stale watchdog anomalies.
    """
    db = mongo_store.get_db()
    now_dt = now or _now()
    now_str = _iso(now_dt)

    reconciled_tasks: list[dict[str, Any]] = []
    orphan_locks_released: list[str] = []
    anomalies_resolved: list[str] = []

    active_progressing = 0
    active_but_frozen = 0
    blocked_count = 0
    retry_exhausted_count = 0

    # 1. Scan all non-terminal tasks
    active_tasks = list(
        db[OPS_TASKS_COL].find(
            {"status": {"$in": ["accepted", "in_progress", "verification", "blocked"]}},
            {"_id": 0},
        )
    )

    for task in active_tasks:
        tid = str(task.get("task_id") or "")
        status = str(task.get("status") or "")
        repo = str(task.get("repo") or "").strip()
        worker_id = str(task.get("worker_id") or "")
        attempt_count = int(task.get("attempt_count") or 1)
        retry_budget = int(task.get("retry_budget") or DEFAULT_RETRY_BUDGET)

        lease_exp = _parse_iso(task.get("lease_expires_at"))
        last_hb = _parse_iso(task.get("last_heartbeat_at"))
        last_prog = _parse_iso(task.get("last_progress_at"))
        is_frozen = bool(task.get("is_frozen"))

        if status == "blocked":
            blocked_count += 1
            # Rule 6: Blocked tasks must never retain repo locks unless active lease
            if repo and not (lease_exp and lease_exp > now_dt):
                if not dry_run:
                    racb_locks.manage_coordination_lock(
                        action="release",
                        resource_id=repo,
                        agent="coordination_liveness",
                        task_id=tid,
                        force=True,
                    )
            continue

        # Check for expired lease
        is_lease_expired = bool(lease_exp and lease_exp <= now_dt)
        # Check for missing heartbeat (> 2x lease time or > 20 mins without HB)
        is_stale_heartbeat = bool(last_hb and (now_dt - last_hb).total_seconds() > 1200)

        # Check for frozen retry storm
        if is_frozen or (task.get("no_progress_heartbeat_count", 0) >= FROZEN_HEARTBEAT_THRESHOLD):
            active_but_frozen += 1
            if attempt_count >= retry_budget:
                retry_exhausted_count += 1
                rec_info = {
                    "task_id": tid,
                    "action": "transition_to_blocked",
                    "reason": "retry_budget_exhausted_frozen",
                    "attempt_count": attempt_count,
                    "retry_budget": retry_budget,
                }
                reconciled_tasks.append(rec_info)
                if not dry_run:
                    if repo:
                        racb_locks.manage_coordination_lock(
                            action="release", resource_id=repo, agent="coordination_liveness", task_id=tid, force=True
                        )
                    db[OPS_TASKS_COL].update_one(
                        {"task_id": tid},
                        {
                            "$set": {
                                "status": "blocked",
                                "blocker": "coordination_liveness:retry_budget_exhausted_frozen",
                                "lease_expires_at": now_str,
                                "cooldown_until": _iso(now_dt + timedelta(seconds=COOLDOWN_SECONDS)),
                                "updated_at": now_str,
                                "updated_by": "coordination_liveness",
                            }
                        },
                    )
                continue

        if is_lease_expired or is_stale_heartbeat:
            # Lease has expired: reconcile task
            if attempt_count >= retry_budget:
                retry_exhausted_count += 1
                target_status = "blocked"
                reason = "lease_expired_retry_exhausted"
            else:
                target_status = "proposed"
                reason = "lease_expired_requeued"

            rec_info = {
                "task_id": tid,
                "action": f"transition_to_{target_status}",
                "reason": reason,
                "attempt_count": attempt_count,
                "retry_budget": retry_budget,
            }
            reconciled_tasks.append(rec_info)

            if not dry_run:
                if repo:
                    racb_locks.manage_coordination_lock(
                        action="release", resource_id=repo, agent="coordination_liveness", task_id=tid, force=True
                    )
                db[OPS_TASKS_COL].update_one(
                    {"task_id": tid},
                    {
                        "$set": {
                            "status": target_status,
                            "blocker": f"coordination_liveness:{reason}" if target_status == "blocked" else None,
                            "worker_id": None,
                            "lease_expires_at": now_str,
                            "updated_at": now_str,
                            "updated_by": "coordination_liveness",
                        }
                    },
                )
        else:
            active_progressing += 1

    # 2. Check for orphan repo locks
    active_locks = list(db[LOCKS_COL].find({"status": "active"}, {"_id": 0}))
    for lock in active_locks:
        ltask_id = lock.get("task_id")
        lresource = lock.get("resource_id")
        lexpiry = _parse_iso(lock.get("expires_at"))

        is_lock_expired = bool(lexpiry and lexpiry <= now_dt)
        associated_task = db[OPS_TASKS_COL].find_one({"task_id": ltask_id}, {"_id": 0}) if ltask_id else None
        task_status = str((associated_task or {}).get("status") or "")

        if is_lock_expired or (associated_task and task_status in ["completed", "cancelled", "superseded", "blocked"]):
            orphan_locks_released.append(lresource)
            if not dry_run:
                racb_locks.manage_coordination_lock(
                    action="release",
                    resource_id=lresource,
                    agent="coordination_liveness",
                    task_id=ltask_id,
                    force=True,
                )

    # 3. Clean stale watchdog anomalies
    open_anomalies = list(db[ANOMALIES_COL].find({"status": "open"}, {"_id": 0}))
    for anomaly in open_anomalies:
        aid = str(anomaly.get("anomaly_id") or "")
        atask_id = str(anomaly.get("task_id") or "")
        if atask_id:
            atask = db[OPS_TASKS_COL].find_one({"task_id": atask_id}, {"_id": 0})
            if atask and atask.get("status") in ["completed", "cancelled", "superseded"]:
                anomalies_resolved.append(aid)
                if not dry_run:
                    db[ANOMALIES_COL].update_one(
                        {"anomaly_id": aid},
                        {"$set": {"status": "resolved", "resolved_at": now_str, "resolver": "coordination_liveness"}},
                    )

    return {
        "ok": True,
        "reconciled_at": now_str,
        "active_progressing": active_progressing,
        "active_but_frozen": active_but_frozen,
        "blocked": blocked_count,
        "retry_exhausted": retry_exhausted_count,
        "orphan_locks_released": orphan_locks_released,
        "stale_tasks_reconciled": len(reconciled_tasks),
        "reconciled_tasks": reconciled_tasks,
        "anomalies_resolved": anomalies_resolved,
    }


def get_coordination_liveness_summary() -> dict[str, Any]:
    """Expose live summary for operational telemetry and health inspection."""
    db = mongo_store.get_db()
    now_dt = _now()

    active_tasks = list(
        db[OPS_TASKS_COL].find(
            {"status": {"$in": ["accepted", "in_progress", "verification"]}},
            {"_id": 0},
        )
    )
    blocked_tasks = list(db[OPS_TASKS_COL].find({"status": "blocked"}, {"_id": 0}))
    active_locks = list(db[LOCKS_COL].find({"status": "active"}, {"_id": 0}))

    progressing = 0
    frozen = 0
    for t in active_tasks:
        if t.get("is_frozen") or (t.get("no_progress_heartbeat_count", 0) >= FROZEN_HEARTBEAT_THRESHOLD):
            frozen += 1
        else:
            progressing += 1

    return {
        "ok": True,
        "checked_at": _iso(now_dt),
        "active_progressing": progressing,
        "active_but_frozen": frozen,
        "blocked_tasks_count": len(blocked_tasks),
        "active_locks_count": len(active_locks),
        "total_active_tasks": len(active_tasks),
    }
