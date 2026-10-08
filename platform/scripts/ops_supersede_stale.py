#!/usr/bin/env python3
"""Marca ops stale como superseded (canonical E2E task conservada)."""
from __future__ import annotations

import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

from raphiia_openai import mongo_store

COL = "ralfia_ops_tasks"
CANONICAL = "ops_096993ac0911"
CORR = "inneros-core-autonomy-model-pin-20261008"


def main() -> int:
    db = mongo_store.get_db()
    res = db[COL].update_many(
        {
            "correlation_id": CORR,
            "task_id": {"$ne": CANONICAL},
            "status": {"$in": ["failed", "awaiting_cursor_claim", "running", "claimed", "verification"]},
        },
        {"$set": {"status": "superseded", "superseded_by": CANONICAL}},
    )
    print({"ok": True, "modified": res.modified_count, "canonical": CANONICAL})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
