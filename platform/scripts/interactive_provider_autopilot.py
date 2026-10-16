#!/usr/bin/env python3
"""Autopilot: Codex + Antigravity, 1 lane per node, competition + claimed task dispatch."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import competition_lane_dispatch as cld
from inneros_core_runtime import interactive_provider_lanes as ipl
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store

PROVIDERS = ("codex", "antigravity")


def _claimed_tasks(provider: str, limit: int = 5) -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    filt = {
        "assignee": provider,
        "status": {"$in": ["claimed", "in_progress", "running"]},
        "claim_token": {"$exists": True},
        "owner_authorized_at": {"$exists": True},
        "provider_execution_started_at": {"$exists": False},
    }
    return list(db[OPS_TASKS_COL].find(filt, {"_id": 0}).sort("claimed_at", 1).limit(limit))


def _tick_provider(provider: str) -> dict[str, Any]:
    ipl.touch_node_liveness(provider)
    slots = ipl.available_slots(provider)
    if slots <= 0:
        return {"ok": True, "provider": provider, "idle": True, "reason": "no_slots", "lanes": ipl.lane_status(provider)}
    started = []
    for task in _claimed_tasks(provider, limit=slots):
        ok, reason = ipl.should_this_node_run_task(provider, task)
        if not ok:
            continue
        tid = str(task.get("task_id") or "")
        if not cld.is_competition_task(task):
            continue
        out = cld.spawn_competition_execute(tid)
        started.append({"task_id": tid, "spawn": out})
        if len(started) >= slots:
            break
    return {
        "ok": True,
        "provider": provider,
        "started": started,
        "lanes": ipl.lane_status(provider),
        "idle": not started,
    }


def main() -> int:
    report = {p: _tick_provider(p) for p in PROVIDERS}
    print(json.dumps({"ok": True, "report": report}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
