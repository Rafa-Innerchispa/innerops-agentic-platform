#!/usr/bin/env python3
"""Best-effort backfill of human_task_id for active/recent ops tasks."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime import human_task_id as hti
from raphiia_openai import mongo_store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=45, help="Look back N days")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, args.days))).isoformat()
    db = mongo_store.get_db()
    rows = list(
        db[OPS_TASKS_COL]
        .find(
            {
                "$or": [
                    {"human_task_id": {"$exists": False}},
                    {"human_task_id": ""},
                ],
                "updated_at": {"$gte": since},
            },
            {"_id": 0},
        )
        .sort("updated_at", -1)
        .limit(max(1, min(args.limit, 5000)))
    )
    changed = 0
    for row in rows:
        out = hti.backfill_task(row, dry_run=not args.apply)
        if out.get("human_task_id"):
            changed += 1
            print(out)
    print({"ok": True, "scanned": len(rows), "updated": changed, "apply": bool(args.apply)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
