"""Independent Integration Guardian for Dev Swarm verification results."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from raphiia_openai import coordination_live, local_execution_plane, mongo_store

WORKERS_COL = "ralfia_dev_swarm_workers"


def _worktree(worker: dict[str, Any]) -> str:
    launch = worker.get("launch") if isinstance(worker.get("launch"), dict) else {}
    wt = launch.get("worktree") if isinstance(launch.get("worktree"), dict) else {}
    return str(wt.get("worktree") or "")


def _commit_head(worker: dict[str, Any]) -> str:
    executor = worker.get("executor") if isinstance(worker.get("executor"), dict) else {}
    commit = executor.get("commit") if isinstance(executor.get("commit"), dict) else {}
    return str(commit.get("head") or executor.get("commit_head") or "").strip()


def verify_worker(worker: dict[str, Any]) -> dict[str, Any]:
    task_id = str(worker.get("task_id") or "")
    executor = worker.get("executor") if isinstance(worker.get("executor"), dict) else {}
    files = list(executor.get("files_touched") or [])
    product_files = list(executor.get("implementation_writes_product") or [])
    test_status = str(executor.get("test_status") or "")
    worktree = _worktree(worker)
    expected_head = _commit_head(worker)
    reasons: list[str] = []
    observed_head = ""

    if not task_id:
        reasons.append("task_id_missing")
    if str(executor.get("status") or "") != "executed":
        reasons.append("executor_not_executed")
    if str(executor.get("outcome") or "") != "PASS":
        reasons.append("executor_outcome_not_pass")
    if test_status != "PASS":
        reasons.append("tests_not_pass")
    if not files:
        reasons.append("files_touched_empty")
    if not product_files:
        reasons.append("product_implementation_empty")
    if not expected_head:
        reasons.append("commit_head_missing")
    if not worktree:
        reasons.append("worktree_missing")
    elif not Path(worktree).exists():
        reasons.append("worktree_not_found")
    else:
        try:
            result = local_execution_plane._run(["git", "rev-parse", "HEAD"], Path(worktree), timeout_seconds=30)
            observed_head = str(result.get("stdout") or "").strip()
            if not result.get("ok") or not observed_head:
                reasons.append("worktree_head_unreadable")
            elif expected_head and observed_head != expected_head:
                reasons.append("commit_head_mismatch")
        except Exception as exc:
            reasons.append(f"head_check_failed:{exc}")

    return {
        "ok": not reasons,
        "task_id": task_id,
        "test_status": test_status,
        "files_touched": files,
        "product_files": product_files,
        "expected_head": expected_head,
        "observed_head": observed_head,
        "reasons": reasons,
    }


def guardian_tick(limit: int = 4, dry_run: bool = False, db: Any | None = None) -> dict[str, Any]:
    database = db if db is not None else mongo_store.get_db()
    lim = max(1, min(int(limit or 4), 12))
    workers = list(database[WORKERS_COL].find(
        {"status": "verification", "executor.status": "executed"}, {"_id": 0}
    ).sort("updated_at", 1).limit(lim))
    checked: list[dict[str, Any]] = []
    for worker in workers:
        verdict = verify_worker(worker)
        checked.append(verdict)
        if dry_run:
            continue
        task_id = str(verdict.get("task_id") or "")
        if not task_id:
            continue
        evidence = {
            "status": "PASS" if verdict["ok"] else "FAIL",
            "guardian": "Integration Guardian",
            "guardian_independent": True,
            "verification": verdict,
        }
        if verdict["ok"]:
            database[WORKERS_COL].update_one({"task_id": task_id}, {"$set": {
                "status": "executed",
                "guardian.status": "PASS",
                "guardian.evidence": evidence,
                "executor.final_status": "PASS",
                "executor.finalized_by": "integration_guardian",
            }})
            coordination_live.update_ops_task_state(task_id, "completed", actor="ralfia", evidence=evidence, force_handoff=True)
        else:
            database[WORKERS_COL].update_one({"task_id": task_id}, {"$set": {
                "status": "blocked",
                "guardian.status": "FAIL",
                "guardian.evidence": evidence,
                "blocker": "integration_guardian_failed",
                "executor.final_status": "FAIL",
                "executor.finalized_by": "integration_guardian",
            }})
            coordination_live.update_ops_task_state(task_id, "blocked", actor="ralfia", evidence=evidence, force_handoff=True)
            coordination_live.heartbeat_ops_task(task_id, "ralfia", next_action="repair Guardian findings", blocker=";".join(verdict["reasons"])[:1000])
    return {
        "ok": all(item.get("ok") for item in checked) if checked else True,
        "guardian": "Integration Guardian",
        "checked": checked,
        "count": len(checked),
        "dry_run": dry_run,
    }
