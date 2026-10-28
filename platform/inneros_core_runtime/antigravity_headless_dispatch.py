"""Spawn versioned Antigravity headless worker (fail-closed; replaces unversioned Intel scripts)."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime import interactive_provider_lanes as ipl
from inneros_core_runtime import cursor_headless_lanes as cursor_lanes
from raphiia_openai import mongo_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def headless_execute_enabled() -> bool:
    return os.getenv("INNEROS_ANTIGRAVITY_HEADLESS_EXECUTE", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _headless_log_path(task_id: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    log_dir = root.parent / "var" / "evidence" / "headless-antigravity"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe = task_id.replace("/", "_")
    return log_dir / f"{safe}-{_now().replace(':', '')}.log"


def _headless_unit_name(task_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id).strip("-.") or "task"
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:10]
    return f"inneros-antigravity-headless-{safe[:88]}-{digest}.service"


def _clear_spawn_reservation(db: Any, task_id: str, host: str) -> None:
    db[OPS_TASKS_COL].update_one(
        {"task_id": task_id, "provider_execution_host": host},
        {
            "$unset": {
                "provider_execution_started_at": "",
                "provider_execution_host": "",
                "headless_execution_started_at": "",
                "headless_execution_host": "",
                "headless_execution_unit": "",
            }
        },
    )


def spawn_headless_execute(task_id: str, *, force_retry: bool = False) -> dict[str, Any]:
    """Reserve lane and start antigravity_ops_headless_execute_one in background."""
    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    if not headless_execute_enabled():
        return {"ok": False, "error": "headless_execute_disabled"}
    if not cursor_lanes.is_ha_execution_node():
        return {"ok": False, "error": "not_ha_execution_node"}
    if ipl.available_slots("antigravity") <= 0 and not force_retry:
        return {"ok": False, "error": "no_available_slots", "lanes": ipl.lane_status("antigravity")}

    host = ipl.hostname()
    db = mongo_store.get_db()
    if force_retry:
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid, "assignee": "antigravity"},
            {
                "$unset": {
                    "provider_execution_started_at": "",
                    "provider_execution_finished_at": "",
                    "headless_execution_started_at": "",
                    "headless_execution_pid": "",
                    "headless_execution_unit": "",
                },
                "$set": {"updated_at": _now()},
            },
        )
    reserved = db[OPS_TASKS_COL].find_one_and_update(
        {
            "task_id": tid,
            "assignee": "antigravity",
            "status": {"$in": ["in_progress", "claimed", "running", "failed", "verification"]},
            "claim_token": {"$exists": True},
            "provider_execution_started_at": {"$exists": False},
        },
        {
            "$set": {
                "provider_execution_started_at": _now(),
                "provider_execution_host": host,
                "headless_execution_started_at": _now(),
                "headless_execution_host": host,
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
    if not py.is_file():
        py = Path(os.getenv("INNEROS_PYTHON") or "python3")
    script = root / "scripts" / "antigravity_ops_headless_execute_one.py"
    log_path = _headless_log_path(tid)
    unit = _headless_unit_name(tid)
    env_file = root / ".env"
    command = [
        "systemd-run",
        "--user",
        "--quiet",
        "--collect",
        f"--unit={unit}",
        "--property=Type=exec",
        f"--property=WorkingDirectory={root}",
        f"--property=EnvironmentFile=-{env_file}",
        f"--property=Environment=PYTHONPATH={root}",
        f"--property=StandardOutput=append:{log_path}",
        f"--property=StandardError=append:{log_path}",
        str(py),
        str(script),
        tid,
    ]
    try:
        launch = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if launch.returncode != 0:
            _clear_spawn_reservation(db, tid, host)
            return {
                "ok": False,
                "task_id": tid,
                "error": "worker_spawn_failed",
                "detail": (launch.stderr or launch.stdout or "systemd_run_failed")[-500:],
            }
        pid_probe = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=MainPID", "--value"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        pid_text = pid_probe.stdout.strip() if pid_probe.returncode == 0 else ""
        pid = int(pid_text) if pid_text.isdigit() else 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        _clear_spawn_reservation(db, tid, host)
        return {"ok": False, "task_id": tid, "error": "worker_spawn_failed", "detail": type(exc).__name__}

    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$set": {
                "headless_execution_pid": pid,
                "headless_execution_unit": unit,
                "headless_log_path": str(log_path),
                "headless_worker_script": str(script.relative_to(root)),
            }
        },
    )
    return {
        "ok": True,
        "task_id": tid,
        "pid": pid,
        "unit": unit,
        "host": host,
        "log_path": str(log_path),
        "script": str(script),
    }
