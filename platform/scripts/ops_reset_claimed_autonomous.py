#!/usr/bin/env python3
"""Vuelve una tarea autonomous autorizada a claimed y opcionalmente re-claim con worktree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task_id")
    p.add_argument("--reclaim", action="store_true", help="Release claim_token and run owner_order_execute")
    args = p.parse_args()
    tid = args.task_id.strip()
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from inneros_core_runtime import ops_deploy_execution_pause as odep
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$set": {
                "status": "queued",
                "do_not_auto_dispatch": True,
                "updated_at": now,
            },
            "$unset": {
                "claim_token": "",
                "claimed_at": "",
                "claimed_by": "",
                "worktree": "",
                "git_baseline_sha": "",
                "headless_execution_pid": "",
                "headless_execution_started_at": "",
                "headless_execution_finished_at": "",
                "provider_execution_started_at": "",
                "provider_execution_finished_at": "",
                "headless_spawn_last": "",
            },
        },
    )
    odep.unlock_owner_autonomous_dispatch(tid)
    out = {"ok": True, "task_id": tid, "reset_at": now}
    if args.reclaim:
        from inneros_core_runtime import interactive_ops_orchestrator as ioo

        task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
        prov = str(task.get("assignee") or "antigravity")
        out["reclaim"] = ioo.owner_order_execute(
            prov,
            task_id=tid,
            owner_actor="RAFAEL",
            channel="ops_reset_claimed_autonomous",
            owner_approved=True,
        )
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())