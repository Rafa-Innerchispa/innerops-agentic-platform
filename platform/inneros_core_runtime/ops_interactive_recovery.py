"""Recovery for orphaned manual / interactive IDE ops tasks."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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

_AMD_ALIASES = frozenset({"ralfiia-amd", "ralphiiaamd", "inneros-5", "inneros-5-lan", "ralphi-ia-amd", "amd"})
_INTEL_ALIASES = frozenset({"ralphi-ia-ver-10", "ralphiia", "ralfiia", "inneros-4", "inneros-4-lan", "ralphi-ia-intel", "ralfiia-intel", "intel"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_host_aliases() -> frozenset[str]:
    host = socket.gethostname().strip().lower()
    env_node = os.getenv("INNEROS_NODE_NAME", "").strip().lower()
    aliases = {"localhost", "127.0.0.1"}
    if host:
        aliases.add(host)
    if env_node:
        aliases.add(env_node)
    if host in _AMD_ALIASES or env_node in _AMD_ALIASES:
        aliases.update(_AMD_ALIASES)
    if host in _INTEL_ALIASES or env_node in _INTEL_ALIASES:
        aliases.update(_INTEL_ALIASES)
    return frozenset(aliases)


def _resolve_git_lock_paths(wt_path: Path) -> list[Path]:
    """Resolve index.lock and HEAD.lock for both standard .git dirs and linked worktree .git files."""
    locks: list[Path] = []
    dot_git = wt_path / ".git"
    try:
        if dot_git.is_file():
            content = dot_git.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                if line.strip().lower().startswith("gitdir:"):
                    raw_target = line.split(":", 1)[1].strip()
                    if raw_target:
                        target_path = Path(raw_target)
                        gitdir = target_path if target_path.is_absolute() else (wt_path / target_path).resolve()
                        locks.append(gitdir / "index.lock")
                        locks.append(gitdir / "HEAD.lock")
        elif dot_git.is_dir():
            locks.append(dot_git / "index.lock")
            locks.append(dot_git / "HEAD.lock")
    except OSError:
        pass
    return locks


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


def is_worker_active(
    task: dict[str, Any],
    *,
    remote_liveness_verifier: Callable[[str, int | None], bool | None] | None = None,
) -> tuple[bool, str]:
    """Verify whether the claimed worker is still active.

    Checks recent heartbeat timestamps, cross-host claim provenance (fail-closed if remote
    host is unverified), live local process IDs, and active worktree git locks (including
    linked worktree .git pointer files).
    Returns (True, reason) if worker is definitely or potentially still running.
    Returns (False, "worker_inactive") only when worker absence is verified.
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

    pid = task.get("headless_execution_pid") or task.get("worker_pid")
    pid_int: int | None = None
    if pid is not None:
        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            pid_int = None

    # 2. Cross-host provenance verification (fail-closed if claim belongs to another host)
    task_host = str(
        task.get("claim_host")
        or task.get("headless_execution_host")
        or task.get("worker_host")
        or ""
    ).strip().lower()
    if task_host and task_host not in _local_host_aliases():
        if task.get("remote_worker_verified_absent") is True:
            pass
        elif remote_liveness_verifier is not None:
            try:
                remote_alive = remote_liveness_verifier(task_host, pid_int)
            except Exception:
                remote_alive = None
            if remote_alive is not False:
                return True, f"remote_host_active_or_unverified:{task_host}"
        else:
            return True, f"remote_host_unverified:{task_host}"
    elif pid_int is not None and pid_int > 0:
        # 3. Local OS process check (only valid when claim belongs to this host)
        try:
            os.kill(pid_int, 0)
            return True, f"worker_pid_{pid_int}_alive"
        except ProcessLookupError:
            pass
        except PermissionError:
            return True, f"worker_pid_{pid_int}_permission_denied"

    # 4. Worktree git lock check (supports both .git/ dir and linked worktree .git pointer file)
    wt = task.get("worktree") or task.get("local_worktree")
    if wt:
        try:
            for lock_path in _resolve_git_lock_paths(Path(str(wt))):
                if lock_path.exists():
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


def recover_orphan_interactive_ops_tasks(
    *,
    limit: int = 20,
    remote_liveness_verifier: Callable[[str, int | None], bool | None] | None = None,
) -> dict[str, Any]:
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
    skipped_active: list[dict[str, Any]] = []
    for task in rows:
        if len(recovered) >= limit:
            break
        if not requires_manual_interactive_lane(task):
            continue
        if has_active_valid_claim(task):
            continue
        # Active worker verification: if PID alive, recent heartbeat, remote host unverified, or worktree locked -> ZERO writes!
        worker_alive, reason = is_worker_active(task, remote_liveness_verifier=remote_liveness_verifier)
        if worker_alive:
            skipped_active.append({"task_id": str(task.get("task_id") or ""), "reason": reason})
            continue
        if _usable_worktree(task) and str(task.get("status") or "") in {"in_progress", "running"}:
            # Worktree present but no claim and worker inactive ? recover so interactive runner can reclaim.
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
    return {"ok": True, "recovered": recovered, "skipped_active": skipped_active, "scanned": len(rows)}
