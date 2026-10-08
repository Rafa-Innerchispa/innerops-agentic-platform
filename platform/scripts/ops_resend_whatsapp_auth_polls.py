#!/usr/bin/env python3
"""Reenvía encuestas Sí/No de autorización ops (bypass dedupe en memoria del proceso)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_ids", nargs="*", help="ops_… (vacío = correlation golden-flow-quad-v2)")
    parser.add_argument("--correlation", default="golden-flow-quad-v2")
    args = parser.parse_args()

    from raphiia_openai import mongo_store
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from inneros_core_runtime.notifications import ops_task_alerts as alerts

    db = mongo_store.get_db()
    tasks: list[dict] = []
    if args.task_ids:
        for tid in args.task_ids:
            doc = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
            if doc:
                tasks.append(doc)
            else:
                print(f"skip missing {tid}")
    else:
        tasks = list(
            db[OPS_TASKS_COL].find(
                {
                    "correlation_id": args.correlation,
                    "status": {"$regex": "^awaiting_"},
                },
                {"_id": 0},
            )
        )

    if not tasks:
        print("no tasks to notify")
        return 1

    for task in tasks:
        tid = task.get("task_id")
        out = alerts.notify_ops_owner_authorization_request(task, force=True)
        print(tid, out.get("ok"), out.get("skipped") or out.get("delivery_mode"), out.get("poll_message_id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
