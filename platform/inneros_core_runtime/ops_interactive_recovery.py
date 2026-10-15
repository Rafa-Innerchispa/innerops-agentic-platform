"""Recovery for orphaned manual / interactive IDE ops tasks."""

from __future__ import annotations

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
