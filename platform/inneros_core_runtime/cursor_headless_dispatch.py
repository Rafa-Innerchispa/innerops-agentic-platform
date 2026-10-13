"""Spawn headless Cursor execute_one worker (shared by autopilot and claim paths)."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def headless_execute_enabled() -> bool:
    return os.getenv("INNEROS_CURSOR_HEADLESS_EXECUTE", "1").strip().lower() in {"1", "true", "yes"}


def _headless_log_path(task_id: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    log_dir = root.parent / "var" / "evidence" / "headless"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe = task_id.replace("/", "_")
    return log_dir / f"{safe}-{_now().replace(':', '')}.log"


def spawn_headless_execute(task_id: str, *, force_retry: bool = False) -> dict[str, Any]:
    """Reserve lane and start cursor_ops_headless_execute_one in background."""
    from inneros_core_runtime import cursor_headless_lanes as lanes

    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    if not headless_execute_enabled():
        return {"ok": False, "error": "headless_execute_disabled"}
    if not lanes.is_ha_execution_node():
        return {"ok": False, "error": "not_ha_execution_node"}
    if lanes.available_slots() <= 0 and not force_retry:
        return {"ok": False, "error": "no_available_slots", "lanes": lanes.lane_status()}

    host = lanes.hostname()
    db = mongo_store.get_db()
    if force_retry:
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid, "assignee": "cursor"},
            {
                "$unset": {
                    "headless_execution_started_at": "",
                    "headless_execution_finished_at": "",
                    "headless_execution_pid": "",
                },
                "$set": {"updated_at": _now()},
            },
        )
    reserved = db[OPS_TASKS_COL].find_one_and_update(
        {
            "task_id": tid,
            "status": {"$in": ["in_progress", "claimed", "running", "failed", "verification"]},
            "claim_token": {"$exists": True},
            "headless_execution_started_at": {"$exists": False},
        },
        {
            "$set": {
                "headless_execution_started_at": _now(),
                "headless_execution_host": host,
                "cursor_execution_host": host,
                "cursor_execution_role": lanes.node_role(),
                "updated_at": _now(),
            },
            "$inc": {"revision": 1},
        },
        return_document=True,
    )
    if not reserved:
        return {"ok": False, "task_id": tid, "error": "not_claimed_or_already_started"}

    root = Path(__file__).resolve().parents[1]
    py = root / "venv" / "bin" / "python3"
    script = root / "scripts" / "cursor_ops_headless_execute_one.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    log_path = _headless_log_path(tid)
    try:
        log_fh = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            [str(py), str(script), "--task-id", tid],
            cwd=str(root),
            env=env,
            start_new_session=True,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
        log_fh.close()
    except OSError as exc:
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid, "headless_execution_host": host},
            {
                "$unset": {
                    "headless_execution_started_at": "",
                    "headless_execution_host": "",
                    "cursor_execution_host": "",
                    "cursor_execution_role": "",
                }
            },
        )
        return {"ok": False, "task_id": tid, "error": "worker_spawn_failed", "detail": type(exc).__name__}

    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {"$set": {"headless_execution_pid": int(proc.pid), "headless_log_path": str(log_path)}},
    )
    return {"ok": True, "task_id": tid, "pid": proc.pid, "host": host, "log_path": str(log_path)}
