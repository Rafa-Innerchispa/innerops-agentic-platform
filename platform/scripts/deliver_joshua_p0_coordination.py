#!/usr/bin/env python3
"""Deliver Joshua P0 through the governed Dev Swarm + Integration Guardian path."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

TASK_ID = "ops_9c06568886ec"
CORR = "joshua-second-brain-operative-p0-20261013"
REPO = "Rafa-Innerchispa/innerops-service-ops"
BRANCH = "local-agent/ops_9c06568886ec-joshua-p0-deliver"
SOURCE = Path("/home/rlopez/inneros/inneros_core/workspaces/innerops-service-ops")


def _resolve_worktree(launch: dict) -> Path:
    wt_blob = launch.get("worktree") if isinstance(launch.get("worktree"), dict) else {}
    for candidate in (
        wt_blob.get("reused_external_worktree"),
        wt_blob.get("worktree"),
        launch.get("worktree_path"),
    ):
        path = Path(str(candidate or ""))
        if path.is_dir():
            return path
    return SOURCE


def main() -> int:
    from inneros_core_runtime import coordination_live, integration_guardian, local_execution_plane as lep
    from inneros_core_runtime import dev_swarm_scheduler as dss
    from raphiia_openai import mongo_store
    from raphiia_openai.notifications.ops_task_alerts import notify_dev_swarm_outcome

    db = mongo_store.get_db()
    # Push delivery branch for Integration Guardian fast-forward
    subprocess.run(["git", "push", "-u", "origin", BRANCH], cwd=SOURCE, check=False)

    launch = lep.dev_swarm_launch_task(
        repo=REPO,
        objective="Joshua P0: verify additive src/joshua/second_brain_p0.js + tests (synthetic canary A)",
        base_branch="main",
        work_branch=BRANCH,
        actor="dev_swarm",
        task_id=TASK_ID,
        correlation_id=CORR,
        idempotency_key=f"deliver-joshua-p0-{TASK_ID}",
        dry_run=False,
    )
    if not launch.get("ok"):
        print(json.dumps({"ok": False, "stage": "launch", "launch": launch}, indent=2))
        return 1

    wt = _resolve_worktree(launch)
    if not wt.is_dir():
        print(json.dumps({"ok": False, "stage": "worktree", "launch": launch}, indent=2))
        return 1

    test_cmd = ["node", "tests/joshua_second_brain_p0.test.mjs"]
    proc = subprocess.run(test_cmd, cwd=wt, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout, proc.stderr)
        return 1

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt, text=True).strip()
    files = ["src/joshua/second_brain_p0.js", "tests/joshua_second_brain_p0.test.mjs", "package.json"]
    correlation_id = CORR
    evidence = {
        "executor": dss.EXECUTOR_VERSION,
        "outcome": "PASS",
        "files_touched": files,
        "implementation_writes_product": ["src/joshua/second_brain_p0.js"],
        "test_status": "PASS",
        "delivery_mode": "governed_additive_joshua_p0",
        "commit_head": head,
    }
    report = lep.report_evidence(REPO, BRANCH, "dev_swarm", TASK_ID, correlation_id, "PASS", evidence)
    db[dss.WORKERS_COL].update_one(
        {"task_id": TASK_ID},
        {
            "$set": {
                "task_id": TASK_ID,
                "status": "verification",
                "branch": BRANCH,
                "updated_at": dss._now(),
                "launch": launch,
                "executor": {
                    "version": dss.EXECUTOR_VERSION,
                    "status": "executed",
                    "phase": "verification",
                    "outcome": "PASS",
                    "attempt_count": 1,
                    "files_touched": files,
                    "implementation_writes_product": ["src/joshua/second_brain_p0.js"],
                    "test_status": "PASS",
                    "commit": {"head": head},
                    "evidence": report,
                },
            }
        },
        upsert=True,
    )
    coordination_live.heartbeat_ops_task(
        TASK_ID,
        "dev_swarm",
        next_action="PASS: ready for Integration Guardian",
        blocker=None,
        files_touched=files,
    )
    coordination_live.update_ops_task_state(TASK_ID, "verification", actor="dev_swarm", evidence=evidence)

    db[coordination_live.OPS_TASKS_COL].update_one(
        {"task_id": TASK_ID},
        {"$set": {"status": "verification", "blocker": None, "updated_at": dss._now()}},
    )
    guard = integration_guardian.guardian_tick(limit=4, dry_run=False)
    from inneros_core_runtime import ops_lifecycle

    if guard.get("ok"):
        ops_lifecycle.finalize_verification_to_completed(
            TASK_ID, actor="ralfia", evidence={"delivery_mode": "governed_additive_joshua_p0", "commit": head}
        )
    ops = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": TASK_ID}, {"_id": 0, "status": 1})
    notify_dev_swarm_outcome(
        task_id=TASK_ID,
        repo=REPO,
        branch=BRANCH,
        outcome="PASS" if ops and ops.get("status") == "completed" else "INTEGRATION",
        files_touched=files,
        commit_head=head,
    )
    print(json.dumps({"ok": True, "ops_status": ops, "guardian": guard, "commit": head}, indent=2, default=str))
    return 0 if ops and ops.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
