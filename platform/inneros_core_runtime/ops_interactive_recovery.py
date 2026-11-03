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
    if isinstance(binding, dict) and binding.get("interactive_execution") is True:
        return True
    top_binding = task.get("execution_binding") or {}
    if isinstance(top_binding, dict) and top_binding.get("interactive_execution") is True:
        return True
    state_binding = (task.get("current_execution_state") or {}).get("execution_binding") or {}
    if isinstance(state_binding, dict) and state_binding.get("interactive_execution") is True:
        return True
    claimed_by = str(task.get("claimed_by") or "").strip().lower()
    if claimed_by in MANUAL_INTERACTIVE_LANES or f"{claimed_by}_interactive" in MANUAL_INTERACTIVE_LANES:
        return True
    preferred = str(task.get("preferred_provider") or "").strip().lower()
    if preferred in MANUAL_INTERACTIVE_LANES or f"{preferred}_interactive" in MANUAL_INTERACTIVE_LANES:
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


def is_worker_active(task: dict[str, Any]) -> tuple[bool, str]:
    """Verify whether the claimed worker is still active.

    Checks recent heartbeat timestamps, live local process IDs, and active worktree git locks.
    Returns (True, reason) if worker is definitely or likely still running.
    Returns (False, "worker_inactive") if no active worker is detected.
    """
    # 1. Heartbeat check (heartbeat within last 180s indicates active worker)
    hb_val = str(task.get("heartbeat_at") or task.get("last_heartbeat") or task.get("heartbeat") or "").strip()
    hb = _parse_ts(hb_val)
    if hb:
        now = datetime.now(timezone.utc)
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        if (now - hb).total_seconds() < 180:
            return True, f"recent_heartbeat_{int((now - hb).total_seconds())}s"

    # 2. Local OS process check (if worker PID is recorded)
    pid = task.get("headless_execution_pid") or task.get("worker_pid")
    if pid is not None:
        try:
            pid_int = int(pid)
            if pid_int > 0:
                import os
                os.kill(pid_int, 0)
                return True, f"worker_pid_{pid_int}_alive"
        except ProcessLookupError:
            pass
        except PermissionError:
            return True, f"worker_pid_{pid}_permission_denied"
        except (ValueError, TypeError):
            pass

    # 3. Worktree git lock check
    wt = task.get("worktree") or task.get("local_worktree")
    if wt:
        try:
            if (Path(str(wt)) / ".git" / "index.lock").exists():
                return True, "worktree_git_locked"
        except OSError:
            pass

    return False, "worker_inactive"


def external_repair_may_auto_claim(task: dict[str, Any]) -> tuple[bool, str]:
    if task.get("do_not_auto_dispatch") is True:
        return False, "do_not_auto_dispatch"
    if requires_manual_interactive_lane(task):
        return False, "manual_interactive_lane"
    return True, "ok"


def recover_orphan_interactive_ops_tasks(*, limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    now_iso = _now()
    filt = {
        "status": {"$in": list(ORPHAN_STATUSES)},
        "$or": [
            {"claim_token": {"$exists": False}},
            {"claim_token": None},
            {"claim_token": ""},
            {"lease_until": {"$lt": now_iso}},
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
        # Active worker verification: if PID alive, recent heartbeat, or worktree locked -> ZERO writes!
        worker_alive, reason = is_worker_active(task)
        if worker_alive:
            continue
        if _usable_worktree(task) and str(task.get("status") or "") in {"in_progress", "running"}:
            # Worktree present but no claim and worker inactive — recover so interactive runner can reclaim.
            pass
        tid = str(task.get("task_id") or "")
        if not tid:
            continue
        target = awaiting_claim_status_for_task(task)
        now = _now()
        cas_filter: dict[str, Any] = {
            "task_id": tid,
            "status": task.get("status"),
        }
        if task.get("claim_token"):
            cas_filter["claim_token"] = task.get("claim_token")
        else:
            cas_filter["claim_token"] = {"$in": [None, ""]}
        if task.get("lease_until") is not None:
            cas_filter["lease_until"] = task.get("lease_until")
        if "revision" in task and task["revision"] is not None:
            cas_filter["revision"] = task["revision"]

        up_res = db[OPS_TASKS_COL].update_one(
            cas_filter,
            {
                "$set": {
                    "status": target,
                    "updated_at": now,
                    "claim_error": "orphan_interactive_recovered",
                    "orphan_recovery_at": now,
                },
                "$unset": {
                    "claim_token": "",
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
        modified = getattr(up_res, "modified_count", None)
        if isinstance(modified, int) and modified < 1:
            # Concurrent renewal or racing recovery occurred; do not declare recovered
            continue

        recovered.append({"task_id": tid, "status": target})
    return {"ok": True, "recovered": recovered, "scanned": len(rows)}
