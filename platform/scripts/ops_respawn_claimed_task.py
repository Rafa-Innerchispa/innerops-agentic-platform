#!/usr/bin/env python3
"""Desbloquea dispatch tras owner auth y reintenta spawn headless en el nodo actual."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task_id")
    p.add_argument("--provider", default="")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    tid = args.task_id.strip()
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from inneros_core_runtime import ops_deploy_execution_pause as odep
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
    if not task:
        print(json.dumps({"ok": False, "error": "task_not_found"}))
        return 1
    prov = (args.provider or task.get("assignee") or "").strip().lower()
    out: dict = {"task_id": tid, "provider": prov, "status_before": task.get("status")}
    if args.dry_run:
        out["would_unlock"] = odep.owner_autonomous_dispatch_unlocked(task)
        out["frozen_before"] = odep.execution_automation_frozen(task)
        print(json.dumps(out, indent=2))
        return 0
    out["unlock"] = odep.unlock_owner_autonomous_dispatch(tid)
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or task
    out["frozen_after"] = odep.execution_automation_frozen(task)
    spawn = None
    if prov == "antigravity":
        from inneros_core_runtime import antigravity_headless_dispatch as agd

        spawn = agd.spawn_headless_execute(tid, force_retry=True)
    elif prov == "codex":
        from inneros_core_runtime import codex_headless_dispatch as cdx

        spawn = cdx.spawn_headless_execute(tid, force_retry=True)
    elif prov == "cursor":
        from inneros_core_runtime import cursor_headless_dispatch as chd

        spawn = chd.spawn_headless_execute(tid, force_retry=True)
    else:
        spawn = {"ok": False, "error": "unsupported_provider"}
    out["spawn"] = spawn
    print(json.dumps(out, indent=2, default=str))
    return 0 if (spawn or {}).get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())