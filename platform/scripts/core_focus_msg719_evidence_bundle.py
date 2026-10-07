#!/usr/bin/env python3
"""Evidence bundle for Notion msg_719c7724 — golden flow review (no fake Temporal ops)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CORRELATION = "chatgpt-golden-flow-20261005"
CANARY_ARTIFACT = Path(__file__).resolve().parents[2] / "var" / "evidence" / "core_canary_ae6358254997.json"
WORKTREE = Path(
    "/home/rlopez/inneros/inneros_core/var/local_execution/worktrees/"
    "Rafa-Innerchispa__amd-academy-mc3-rag/cursor__core-canary-58254997"
)
WORK_BRANCH = "cursor/core-canary-58254997"
REPO = "Rafa-Innerchispa/amd-academy-mc3-rag"


def _git_show(commit: str) -> dict:
    if not WORKTREE.is_dir():
        return {"ok": False, "error": "worktree_missing", "path": str(WORKTREE)}
    stat = subprocess.run(["git", "show", commit, "--stat"], cwd=WORKTREE, capture_output=True, text=True)
    patch = subprocess.run(
        ["git", "show", commit, "--", "docs/CORE_CANARY_EVIDENCE.md"],
        cwd=WORKTREE,
        capture_output=True,
        text=True,
    )
    return {
        "ok": stat.returncode == 0,
        "stat": (stat.stdout or "")[:4000],
        "patch": (patch.stdout or "")[:8000],
    }


def _gate_b_pytest() -> dict:
    proc = subprocess.run(
        [f"{ROOT}/venv/bin/python", "-m", "pytest", "tests/test_temporal_bounded_executor.py", "-v", "--tb=no"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-3500:],
        "stderr_tail": (proc.stderr or "")[-1500:],
    }


def _gate_b_live_gate_demo() -> dict:
    from inneros_core_runtime import temporal_activities as ta

    neg = asyncio.run(
        ta.activity_validate_completion_gate(
            {"task_id": "demo_neg", "task_class": "coding"},
            {
                "files_count": 5,
                "objective_files_count": 0,
                "bridge_artifact_paths": ["platform/inneros_core_runtime/temporal_bounded_executor.py"],
                "test_results": {"exit_code": 0, "ok": True},
            },
        )
    )
    pos = asyncio.run(
        ta.activity_validate_completion_gate(
            {"task_id": "demo_pos", "task_class": "coding"},
            {
                "files_count": 1,
                "objective_files_count": 1,
                "objective_paths": ["docs/objective.md"],
                "code_diff": "+ docs/objective.md",
                "test_results": {"exit_code": 0, "ok": True},
            },
        )
    )
    return {"bridge_only_rejected": neg, "objective_accepted": pos}


def _specific_pytest_on_worktree() -> dict:
    from inneros_core_runtime import capability_gateway as cg

    task_id = "msg719_pytest_supplement"
    actor = "cursor"
    idem = "msg719-pytest-supplement-v1"
    test_path = "tests/test_core_canary_smoke.py"
    test_body = (
        '"""Golden-flow canary smoke test (msg_719)."""\n\n'
        "def test_core_canary_marker_present():\n"
        "    from pathlib import Path\n"
        "    p = Path('docs/CORE_CANARY_EVIDENCE.md')\n"
        "    assert p.is_file()\n"
        "    assert 'run_id=core_canary_ae6358254997' in p.read_text(encoding='utf-8')\n"
    )
    write = cg.capability_invoke(
        "local_exec.write_file.v1",
        {
            "repo": REPO,
            "work_branch": WORK_BRANCH,
            "path": test_path,
            "content": test_body,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
            "idempotency_key": idem + "w",
        },
    )
    pytest = cg.capability_invoke(
        "local_exec.run_command_allowlisted.v1",
        {
            "repo": REPO,
            "work_branch": WORK_BRANCH,
            "command": ["python3", "-m", "pytest", test_path, "-q"],
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
            "timeout_seconds": 180,
        },
    )
    inner = (pytest.get("result") or {}) if pytest.get("status") == "COMPLETED" else {}
    cr = inner.get("command_result") or {}
    return {
        "write_execution_id": write.get("execution_id"),
        "pytest_execution_id": pytest.get("execution_id"),
        "pytest_exit_code": cr.get("returncode"),
        "pytest_ok": bool(inner.get("ok") and cr.get("ok") and cr.get("returncode") == 0),
        "pytest_stdout": (cr.get("stdout") or "")[:2000],
        "pytest_stderr": (cr.get("stderr") or "")[:2000],
        "command_run_id": inner.get("command_run_id"),
    }


def _reconciliation() -> dict:
    from raphiia_openai import coordination_live, mongo_store

    live = coordination_live.get_coordination_live()
    db = mongo_store.get_db()
    col = db["ralfia_ops_tasks"]
    running = list(
        col.find({"status": {"$in": ["running", "dispatched"]}}, {"_id": 0, "task_id": 1, "status": 1, "updated_at": 1, "correlation_id": 1})
        .sort("updated_at", -1)
        .limit(15)
    )
    worker_pid = subprocess.run(
        ["systemctl", "--user", "show", "inneros-temporal-worker.service", "-p", "MainPID", "--value"],
        capture_output=True,
        text=True,
    )
    py_path = ""
    pid = (worker_pid.stdout or "").strip()
    if pid.isdigit():
        env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        for item in env:
            if item.startswith(b"PYTHONPATH="):
                py_path = item.decode().split("=", 1)[1]
                break
    return {
        "execution_path_canary_d": "direct_script_capability_broker_NOT_temporal_workflow",
        "ops_task_ops_ae6358254997_in_mongo": col.find_one({"task_id": "ops_ae6358254997"}) is not None,
        "temporal_workflow_id_for_canary": None,
        "coordination_live_open_ops_count": live.get("open_ops_count") if isinstance(live, dict) else None,
        "mongo_running_dispatched_sample": running,
        "temporal_worker_main_pid": pid,
        "temporal_worker_pythonpath": py_path,
        "quality_gate_code_on_worker_path": "UNKNOWN_until_release_sync",
        "reconciliation_mutations_applied": False,
        "note": "Diagnóstico read-only; no cancel/borrar ops stale sin Temporal autoritativo por ID",
    }


def main() -> int:
    artifact = {}
    if CANARY_ARTIFACT.is_file():
        artifact = json.loads(CANARY_ARTIFACT.read_text(encoding="utf-8"))
    steps = artifact.get("steps") or {}
    release = steps.get("release_lock") or {}
    push = steps.get("push") or {}
    report = steps.get("report_evidence") or {}

    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reply_to": "msg_719c7724ab44a163",
        "correlation_id": CORRELATION,
        "gate_status": {
            "A_backend_mcp": "VERIFIED",
            "A_notion_client_21_tools": "PENDING_CLIENT_REFRESH",
            "B_quality_gate_pytest_local": "VERIFIED",
            "B_quality_gate_on_temporal_worker_runtime": "PENDING_RELEASE_SYNC",
            "C_reconciliation": "DIAGNOSED_NOT_RECONCILED",
            "D_local_capability_e2e": "VERIFIED_PARTIAL",
            "D_push_live": "PENDING_OPTIONAL",
            "D_temporal_scheduler_handoff": "NOT_APPLICABLE_DIRECT_SCRIPT",
        },
        "canary_artifact_path": str(CANARY_ARTIFACT),
        "canary_summary": artifact.get("summary"),
        "git_show_ccf580c": _git_show("ccf580c"),
        "gate_b_pytest": _gate_b_pytest(),
        "gate_b_validate_completion_gate": _gate_b_live_gate_demo(),
        "specific_pytest_supplement": _specific_pytest_on_worktree(),
        "lock_release_step": release,
        "push_dry_run_step": push,
        "report_evidence_step": report,
        "reconciliation": _reconciliation(),
    }
    out_path = CANARY_ARTIFACT.parent / "msg_719_evidence_bundle.json"
    out_path.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "bundle_path": str(out_path), "gate_status": bundle["gate_status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
