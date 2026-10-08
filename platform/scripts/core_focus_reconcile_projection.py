#!/usr/bin/env python3
"""Read-only reconciliation report for golden-flow ops projection (Gate C)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CORRELATION = "chatgpt-golden-flow-20261005"


def main() -> int:
    from raphiia_openai import coordination_live, mongo_store

    db = mongo_store.get_db()
    col = db[coordination_live.OPS_TASKS_COL]
    now = datetime.now(timezone.utc)
    query = {
        "$or": [
            {"correlation_id": CORRELATION},
            {"status": {"$in": ["running", "dispatched", "pending_human_review"]}},
        ]
    }
    rows = list(
        col.find(query, {"_id": 0, "task_id": 1, "status": 1, "correlation_id": 1, "updated_at": 1, "assignee": 1})
        .sort("updated_at", -1)
        .limit(50)
    )
    stale_running = []
    for row in rows:
        if row.get("status") not in ("running", "dispatched"):
            continue
        updated = str(row.get("updated_at") or "")
        stale_running.append(row)
    report = {
        "ok": True,
        "correlation_id": CORRELATION,
        "scanned": len(rows),
        "stale_running_count": len(stale_running),
        "stale_running_sample": stale_running[:15],
        "note": "read_only_report_no_status_mutation",
        "generated_at": now.isoformat(),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
