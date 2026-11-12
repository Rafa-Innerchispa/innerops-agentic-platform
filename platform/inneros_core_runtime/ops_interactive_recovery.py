"""Recovery for orphaned manual / interactive IDE ops tasks."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime.ops_awaiting_claim import awaiting_claim_status_for_task
from raphiia_openai import mongo_store

MANUAL_INTERACTIVE_LANES = frozenset(
    {
        "local_manual_antigravity",
        "manual_interactive",
        "antigravity_interactive",
        "cursor_interactive",
        "codex_interactive",
        "gemini_interactive",
    }
)

ORPHAN_STATUSES = ("accepted", "in_progress", "running", "claimed")

# Recovery grace is deliberately larger than the claim-validity grace: a lease
# must be plainly dead (no renewal racing us) before the task is reclaimable.
EXPIRED_LEASE_RECOVERY_GRACE_SECONDS = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def requires_manual_interactive_lane(task: dict[str, Any]) -> bool:
    if task.get("do_not_auto_dispatch") is True:
        return True
    lane = str(task.get("execution_lane") or "").strip().lower()
    if lane in MANUAL_INTERACTIVE_LANES or lane.endswith("_interactive"):
        return True
    binding = ((task.get("evidence") or {}).get("execution_binding") or {})
    if binding.get("interactive_execution") is True:
        return True
    return False


def _usable_worktree(task: dict[str, Any]) -> bool:
    wt = task.get("worktree") or task.get("local_worktree")
    if not wt:
        return False
    try:
        return Path(str(wt)).is_dir()
    except OSError:
        return False


def has_active_valid_claim(task: dict[str, Any], *, grace_seconds: int = 30) -> bool:
    token = (task.get("claim_token") or "").strip()
    if not token:
        return False
    lease = _parse_ts(str(task.get("lease_until") or ""))
    if lease is None:
        return True
    now = datetime.now(timezone.utc)
    if lease.tzinfo is None:
        lease = lease.replace(tzinfo=timezone.utc)
    if lease > now:
        return True
    return (now - lease).total_seconds() <= grace_seconds


def external_repair_may_auto_claim(task: dict[str, Any]) -> tuple[bool, str]:
    if task.get("do_not_auto_dispatch") is True:
        return False, "do_not_auto_dispatch"
    if requires_manual_interactive_lane(task):
        return False, "manual_interactive_lane"
    return True, "ok"


def recover_orphan_interactive_ops_tasks(*, limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt = {
        "status": {"$in": list(ORPHAN_STATUSES)},
        "$or": [
            {"claim_token": {"$exists": False}},
            {"claim_token": None},
            {"claim_token": ""},
        ],
    }
    rows = list(db[OPS_TASKS_COL].find(filt, {"_id": 0}).sort("updated_at", 1).limit(max(5, min(limit * 4, 80))))
    recovered: list[dict[str, Any]] = []
    for task in rows:
        if len(recovered) >= limit:
            break
        if not requires_manual_interactive_lane(task):
            continue
        if has_active_valid_claim(task):
            continue
        if _usable_worktree(task) and str(task.get("status") or "") in {"in_progress", "running"}:
            # Worktree present but no claim — still recover so interactive runner can reclaim.
            pass
        tid = str(task.get("task_id") or "")
        if not tid:
            continue
        target = awaiting_claim_status_for_task(task)
        now = _now()
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid, "claim_token": {"$in": [None, ""]}},
            {
                "$set": {
                    "status": target,
                    "updated_at": now,
                    "claim_error": "orphan_interactive_recovered",
                    "orphan_recovery_at": now,
                },
                "$unset": {
                    "claimed_at": "",
                    "lease_until": "",
                    "claimed_by": "",
                    "claim_host": "",
                    "headless_execution_started_at": "",
                    "headless_execution_pid": "",
                    "headless_execution_host": "",
                },
                "$inc": {"revision": 1},
            },
        )
        recovered.append({"task_id": tid, "status": target})
    return {"ok": True, "recovered": recovered, "scanned": len(rows)}


def recover_expired_lease_interactive_ops_tasks(
    *,
    limit: int = 20,
    grace_seconds: int = EXPIRED_LEASE_RECOVERY_GRACE_SECONDS,
) -> dict[str, Any]:
    """Release interactive tasks whose lease expired without execution.

    Complements :func:`recover_orphan_interactive_ops_tasks`, which only sees
    tasks *without* a claim token. These tasks hold a token whose lease is
    long dead: no live owner can still be working under it, so the task is
    returned to its awaiting-claim status instead of rotting in ``claimed``.
    The compare-and-swap pins the exact observed ``lease_until`` so a
    concurrent renewal always wins the race.
    """
    db = mongo_store.get_db()
    started = datetime.now(timezone.utc)
    filt = {
        "status": {"$in": list(ORPHAN_STATUSES)},
        "claim_token": {"$nin": [None, ""]},
        "lease_until": {"$nin": [None, ""]},
    }
    rows = list(db[OPS_TASKS_COL].find(filt, {"_id": 0}).sort("updated_at", 1).limit(max(5, min(limit * 4, 80))))
    now = datetime.now(timezone.utc)
    recovered: list[dict[str, Any]] = []
    for task in rows:
        if len(recovered) >= limit:
            break
        if not requires_manual_interactive_lane(task):
            continue
        if task.get("execution_stop"):
            continue
        lease = _parse_ts(str(task.get("lease_until") or ""))
        if lease is None:
            continue
        if lease.tzinfo is None:
            lease = lease.replace(tzinfo=timezone.utc)
        if (now - lease).total_seconds() <= max(0, grace_seconds):
            continue
        tid = str(task.get("task_id") or "")
        token = str(task.get("claim_token") or "")
        lease_raw = str(task.get("lease_until") or "")
        if not tid or not token:
            continue
        target = awaiting_claim_status_for_task(task)
        stamp = _now()
        res = db[OPS_TASKS_COL].update_one(
            {"task_id": tid, "claim_token": token, "lease_until": lease_raw},
            {
                "$set": {
                    "status": target,
                    "updated_at": stamp,
                    "claim_error": "expired_lease_recovered",
                    "lease_recovery_at": stamp,
                    "recovered_from_status": str(task.get("status") or ""),
                },
                "$unset": {
                    "claimed_at": "",
                    "lease_until": "",
                    "claimed_by": "",
                    "claim_host": "",
                    "claim_token": "",
                    "headless_execution_started_at": "",
                    "headless_execution_pid": "",
                    "headless_execution_host": "",
                },
                "$inc": {"revision": 1},
            },
        )
        if getattr(res, "matched_count", 1) == 0:
            continue
        recovered.append({"task_id": tid, "status": target})
    if recovered:
        try:
            from inneros_core_runtime import self_heal_metrics as _shm

            _shm.record_self_heal_incident(
                {
                    "service_id": "ops-coordination-leases",
                    "repair_action": "recover_expired_lease_interactive_ops_tasks",
                    "repair_action_ok": True,
                    "verified_recovered": True,
                    "verification_method": "cas_matched_count",
                    "repair_duration_seconds": round(
                        (datetime.now(timezone.utc) - started).total_seconds(), 3
                    ),
                    "automatic": True,
                    "node": socket.gethostname(),
                    "evidence_refs": [entry["task_id"] for entry in recovered],
                    "details": {"recovered": recovered, "scanned": len(rows)},
                }
            )
        except Exception:
            pass
    return {"ok": True, "recovered": recovered, "scanned": len(rows)}
