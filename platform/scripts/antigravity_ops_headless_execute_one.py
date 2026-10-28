#!/usr/bin/env python3
"""Versioned Antigravity headless worker — fail-closed unless real git/tests evidence exists.

Unversioned Intel scripts that call Gemini text-only must not complete ops tasks.
Use interactive_ops_runner.complete_ops_task after committed_objective_receipt proof.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import interactive_ops_runner as ior
from inneros_core_runtime import ops_completion_policy as ocp
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
    token = str(task.get("claim_token") or "").strip()
    if not token:
        print(json.dumps({"ok": False, "error": "claim_token_required", "task_id": tid}))
        return 2
    blocked = {
        "ok": False,
        "error": "antigravity_headless_requires_bounded_executor",
        "task_id": tid,
        "hint": (
            "Do not complete from Gemini text-only API. Run bounded tools, "
            "committed_objective_receipt, tests, then antigravity_complete_ops_task."
        ),
        "policy": "ops_completion_policy_v2_fail_closed",
    }
    if ocp.is_text_only_headless_evidence({"headless_primary": "antigravity_gemini_api"}):
        out = ior.complete_ops_task(
            "antigravity",
            tid,
            claim_token=token,
            status="blocked",
            evidence={
                "notes": "antigravity_ops_headless_execute_one_fail_closed",
                "headless_primary": "antigravity_gemini_api",
                "blocked_reason": blocked["error"],
            },
        )
        print(json.dumps({**blocked, "complete": out}, default=str))
        return 1
    print(json.dumps(blocked))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
