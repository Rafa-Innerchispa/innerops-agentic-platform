"""Shared atomic reserve + spawn for paid IDE headless workers."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime import headless_worker_runtime as hwr
from inneros_core_runtime.ops_headless_execution_policy import (
    MAX_AUTOMATIC_DISPATCHES,
    headless_denial,
)
from raphiia_openai import mongo_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def spawn_paid_headless(
    task_id: str,
    *,
    provider: str,
    enabled: Callable[[], bool],
    is_ha_node: Callable[[], bool],
    available_slots: Callable[[], int],
    hostname: Callable[[], str],
    node_role: Callable[[], str] | None,
    unit_name_for: Callable[[str], str],
    log_path_for: Callable[[str], Path],
    execute_script: Path,
    worker_argv: Callable[[str, Path], list[str]],
    clear_reservation: Callable[[Any, str, str], None],
    force_retry: bool = False,
    extra_set_on_reserve: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = (task_id or "").strip()
    prov = provider.strip().lower()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    if not enabled():
        return {"ok": False, "error": "headless_execute_disabled"}
    if not is_ha_node():
        return {"ok": False, "error": "not_ha_execution_node"}
    if available_slots() <= 0 and not force_retry:
        return {"ok": False, "error": "no_available_slots"}

    host = hostname()
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}) or {}
    denied = headless_denial(task, provider=prov)
    if denied:
        return {"ok": False, "task_id": tid, "error": denied}
    if force_retry:
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid, "assignee": prov},
            {
                "$unset": {
                    "provider_execution_started_at": "",
                    "provider_execution_finished_at": "",
                    "headless_execution_started_at": "",
                    "headless_execution_finished_at": "",
                    "headless_execution_pid": "",
                    "headless_execution_unit": "",
                },
                "$set": {"updated_at": _now()},
            },
        )
    reserve_set = {
        "provider_execution_started_at": _now(),
        "provider_execution_host": host,
        "headless_execution_started_at": _now(),
        "headless_execution_host": host,
        "updated_at": _now(),
    }
    if extra_set_on_reserve:
        reserve_set.update(extra_set_on_reserve)
    if node_role is not None:
        reserve_set["cursor_execution_host"] = host
        reserve_set["cursor_execution_role"] = node_role()

    reserved = db[OPS_TASKS_COL].find_one_and_update(
        {
            "task_id": tid,
            "assignee": prov,
            "status": {"$in": ["in_progress", "claimed", "running"]},
            "provider_execution_started_at": {"$exists": False},
            "headless_execution_started_at": {"$exists": False},
            "do_not_auto_dispatch": {"$ne": True},
            "payload.do_not_auto_dispatch": {"$ne": True},
            "superseded_by": {"$in": [None, ""]},
            "execution_stop": {"$exists": False},
            "claim_token": task["claim_token"],
            "owner_authorized_at": task["owner_authorized_at"],
            "headless_last_result.completion_submitted": {"$ne": True},
            "$or": [
                {"headless_dispatch_attempts": {"$exists": False}},
                {"headless_dispatch_attempts": {"$lt": MAX_AUTOMATIC_DISPATCHES, "$gte": 0}},
            ],
            "execution_paused_for_deploy": {"$ne": True},
        },
        {"$set": reserve_set, "$inc": {"revision": 1, "headless_dispatch_attempts": 1}},
        return_document=True,
    )
    if not reserved:
        return {"ok": False, "task_id": tid, "error": "not_claimed_or_already_started"}

    root = Path(__file__).resolve().parents[1]
    py = hwr.resolve_headless_python(platform_root=root)
    log_path = log_path_for(tid)
    unit = unit_name_for(tid)
    env_file = root / ".env"
    worker_cmd = worker_argv(tid, execute_script)
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
        *worker_cmd,
    ]

    try:
        launch, unit = hwr.systemd_run_transient(unit=unit, command=command, cwd=root)
        if launch.returncode != 0:
            clear_reservation(db, tid, host)
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
        clear_reservation(db, tid, host)
        return {"ok": False, "task_id": tid, "error": "worker_spawn_failed", "detail": type(exc).__name__}

    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$set": {
                "headless_execution_pid": pid,
                "headless_execution_unit": unit,
                "headless_log_path": str(log_path),
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
        "provider": prov,
    }
