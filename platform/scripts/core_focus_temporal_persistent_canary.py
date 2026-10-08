#!/usr/bin/env python3
"""Start one real ops_task -> Temporal workflow for golden-flow fixture (msg_b35)."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CORRELATION = "chatgpt-golden-flow-20261005"
REPO = "Rafa-Innerchispa/amd-academy-mc3-rag"
IDEM = "msg_b35-temporal-persistent-canary-20261007-v4-full-e2e"


def main() -> int:
    from inneros_core_runtime import coordination_live
    from raphiia_openai import mongo_store

    created = coordination_live.create_ops_task(
        assignee="dev_swarm",
        title="Core focus Temporal persistent canary (amd-academy fixture)",
        checklist=[
            "Write docs/TEMPORAL_CANARY.md with task_id marker",
            "Run python3 -m pytest tests/test_core_canary_smoke.py -q",
        ],
        evidence_required=["workflow_id", "run_id", "test_exit_code", "head_sha"],
        priority="p0",
        from_agent="CURSOR",
        correlation_id=CORRELATION,
        related_project=REPO,
        repo=REPO,
        base_ref="main",
        work_branch="cursor/temporal-canary-v4-full-e2e",
        task_class="coding",
        execution_lane="local_dev_swarm",
        idempotency_key=IDEM,
        source_message_id="msg_b35e6ee4c22f1ca0",
        objective="Add docs/TEMPORAL_CANARY.md marker and pass tests/test_core_canary_smoke.py",
        verify_tests=["tests/test_core_canary_smoke.py"],
        required_objective_paths=["docs/TEMPORAL_CANARY.md"],
    )
    if not created.get("ok"):
        print(json.dumps({"ok": False, "stage": "create_ops_task", "created": created}, indent=2))
        return 1

    task_id = created["task_id"]
    workflow_id = created.get("workflow_id")
    run_id = created.get("run_id")
    deadline = time.time() + 420
    final = None
    while time.time() < deadline:
        doc = mongo_store.get_db()["ralfia_ops_tasks"].find_one({"task_id": task_id}, {"_id": 0})
        st = (doc or {}).get("status")
        if st in ("completed", "failed", "pending_human_review", "cancelled"):
            final = doc
            break
        time.sleep(5)

    out = {
        "ok": bool(final and final.get("status") == "completed"),
        "task_id": task_id,
        "workflow_id": workflow_id,
        "temporal_run_id": run_id,
        "final_status": (final or {}).get("status"),
        "final_evidence": (final or {}).get("evidence"),
        "correlation_id": CORRELATION,
        "repo": REPO,
        "idempotency_key": IDEM,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    path = f"/home/rlopez/inneros/inneros_core/var/evidence/temporal_persistent_canary_{task_id}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"summary": out, "create_response": created, "final_task": final}, fh, indent=2, default=str)
    out["artifact_path"] = path
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
