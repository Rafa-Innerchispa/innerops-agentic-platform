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
from inneros_core_runtime import cursor_headless_lanes as cursor_lanes
from inneros_core_runtime import headless_worker_runtime as hwr
from inneros_core_runtime import interactive_provider_lanes as ipl
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
    from inneros_core_runtime import ops_paid_headless_dispatch_core as phd

    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "antigravity_ops_headless_execute_one.py"
    return phd.spawn_paid_headless(
        task_id,
        provider="antigravity",
        enabled=headless_execute_enabled,
        is_ha_node=cursor_lanes.is_ha_execution_node,
        available_slots=lambda: ipl.available_slots("antigravity"),
        hostname=ipl.hostname,
        node_role=None,
        unit_name_for=_headless_unit_name,
        log_path_for=_headless_log_path,
        execute_script=script,
        worker_argv=lambda tid, path: [str(path), tid],
        clear_reservation=_clear_spawn_reservation,
        force_retry=force_retry,
    )
