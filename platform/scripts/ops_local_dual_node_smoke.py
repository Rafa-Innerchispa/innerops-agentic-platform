#!/usr/bin/env python3
"""Smoke: local Dev Swarm eligibility + último worker en este nodo (Intel/AMD)."""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TASK_IDS = ("ops_446a47bf778d", "ops_e8c6e290c53f")


def main() -> int:
    from inneros_core_runtime import dev_swarm_scheduler as dss
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    host = socket.gethostname()
    tasks = []
    for tid in TASK_IDS:
        row = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
        ok, reason, repo = dss._eligible_reason(row) if row else (False, "missing", None)
        tasks.append(
            {
                "task_id": tid,
                "status": row.get("status"),
                "assignee": row.get("assignee"),
                "eligible": ok,
                "reason": reason,
                "repo": repo,
            }
        )
    workers = list(
        db["ralfia_dev_swarm_workers"].find({}, {"_id": 0, "worker_id": 1, "status": 1, "repo": 1, "task_id": 1, "updated_at": 1})
        .sort("updated_at", -1)
        .limit(5)
    )
    cap = dss.capacity_status()
    print(
        json.dumps(
            {
                "ok": True,
                "host": host,
                "tasks": tasks,
                "capacity_admittable": (cap.get("recommendation") or {}).get("admittable_now"),
                "recent_workers": workers,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
