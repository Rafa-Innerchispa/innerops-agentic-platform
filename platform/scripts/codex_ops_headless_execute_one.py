#!/usr/bin/env python3
"""Versioned Codex headless worker — bounded canary or owner-approved Codex CLI exec."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import interactive_provider_bounded_executor as ipbe
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    args = parser.parse_args()
    tid = args.task_id.strip()
    task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
    if not task:
        print(json.dumps({"ok": False, "error": "task_not_found", "task_id": tid}))
        return 2
    result = ipbe.execute_claimed_task(tid, "codex")
    print(json.dumps(result, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
