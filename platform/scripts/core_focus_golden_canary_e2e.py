#!/usr/bin/env python3
"""Integrated golden-flow canary for msg_b257 / chatgpt-golden-flow-20261005 (Gate D).

MCP capability broker -> LEP lease/worktree -> bounded file -> allowlisted verify -> evidence.
No push/MR unless --live-push; default dry_run on push.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CORRELATION = "chatgpt-golden-flow-20261005"
DEFAULT_REPO = "Rafa-Innerchispa/amd-academy-mc3-rag"


def _run_id() -> str:
    return f"core_canary_{uuid.uuid4().hex[:12]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--live-push", action="store_true")
    args = parser.parse_args()

    from inneros_core_runtime import capability_gateway as cg
    from inneros_core_runtime import local_execution_plane as lep

    run_id = _run_id()
    task_id = f"ops_{run_id.replace('core_canary_', '')[:12]}"
    actor = "cursor"
    work_branch = f"cursor/core-canary-{run_id[-8:]}"
    idem = hashlib.sha256(f"{CORRELATION}|{run_id}|{args.repo}".encode()).hexdigest()[:24]
    started = datetime.now(timezone.utc).isoformat()
    steps: dict[str, object] = {}

    def cap(cap_id: str, parameters: dict) -> dict:
        return cg.capability_invoke(cap_id, parameters, idempotency_key=f"{idem}-{cap_id}")

    steps["capability_search_lep"] = cg.capability_search("local execution repo", max_results=5)
    steps["inspect"] = cap(
        "local_exec.inspect_repo.v1",
        {"repo": args.repo},
    )
    steps["resolve_runtime"] = cap(
        "project_runtime.resolve.v1",
        {"repo": args.repo, "node": "amd"},
    )
    steps["acquire_lock"] = cap(
        "local_exec.acquire_lock.v1",
        {
            "repo": args.repo,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
            "ttl_seconds": 900,
        },
    )
    steps["worktree"] = cap(
        "local_exec.create_worktree.v1",
        {
            "repo": args.repo,
            "base_branch": "main",
            "work_branch": work_branch,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
            "idempotency_key": idem,
        },
    )
    marker_path = "docs/CORE_CANARY_EVIDENCE.md"
    marker_body = (
        f"# Core canary evidence\n\nrun_id={run_id}\ncorrelation={CORRELATION}\n"
        f"task_id={task_id}\nbranch={work_branch}\n"
    )
    steps["write_file"] = cap(
        "local_exec.write_file.v1",
        {
            "repo": args.repo,
            "work_branch": work_branch,
            "path": marker_path,
            "content": marker_body,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
            "idempotency_key": idem + "w",
        },
    )
    steps["verify_cmd"] = cap(
        "local_exec.run_command_allowlisted.v1",
        {
            "repo": args.repo,
            "work_branch": work_branch,
            "command": ["git", "status", "--short", "--branch"],
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
            "timeout_seconds": 120,
        },
    )
    verify_payload = steps.get("verify_cmd")
    verify_ok = False
    if isinstance(verify_payload, dict) and verify_payload.get("status") == "COMPLETED":
        inner = verify_payload.get("result") or {}
        cr = inner.get("command_result") or inner.get("status") or {}
        if isinstance(cr, dict):
            out = (cr.get("stdout") or "") + (cr.get("stderr") or "")
        else:
            out = str(cr)
        verify_ok = (
            "CORE_CANARY_EVIDENCE.md" in out
            or marker_path.split("/")[-1] in out
            or "docs/" in out
            or " docs/" in out
        )
    steps["verify_ok"] = verify_ok
    steps["commit"] = cap(
        "local_exec.commit_branch.v1",
        {
            "repo": args.repo,
            "work_branch": work_branch,
            "message": f"docs: core golden canary evidence ({run_id})",
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
            "idempotency_key": idem + "c",
        },
    )
    sha = ""
    commit_payload = steps.get("commit")
    if isinstance(commit_payload, dict):
        inner = commit_payload.get("result") or {}
        sha = str(inner.get("head") or inner.get("commit_sha") or "").strip()

    steps["push"] = cap(
        "local_exec.push_branch.v1",
        {
            "repo": args.repo,
            "work_branch": work_branch,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
            "idempotency_key": idem + "p",
            "dry_run": not args.live_push,
        },
    )
    evidence = {
        "run_id": run_id,
        "task_id": task_id,
        "correlation_id": CORRELATION,
        "repo": args.repo,
        "work_branch": work_branch,
        "head_sha": sha,
        "marker_path": marker_path,
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    steps["report_evidence"] = cap(
        "local_exec.report_evidence.v1",
        {
            "repo": args.repo,
            "work_branch": work_branch,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
            "status": "core_canary_completed",
            "evidence": evidence,
        },
    )
    steps["release_lock"] = cap(
        "local_exec.release_lock.v1",
        {
            "repo": args.repo,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": CORRELATION,
        },
    )

    def step_ok(name: str) -> bool:
        payload = steps.get(name)
        if not isinstance(payload, dict):
            return False
        if payload.get("status") == "COMPLETED":
            inner = payload.get("result") or {}
            return bool(inner.get("ok"))
        return bool(payload.get("ok"))

    required = [
        "inspect",
        "acquire_lock",
        "worktree",
        "write_file",
        "commit",
        "report_evidence",
        "release_lock",
    ]
    ok = all(step_ok(n) for n in required) and bool(steps.get("verify_ok")) and step_ok("verify_cmd")
    out = {
        "ok": ok,
        "run_id": run_id,
        "task_id": task_id,
        "correlation_id": CORRELATION,
        "repo": args.repo,
        "work_branch": work_branch,
        "head_sha": sha,
        "steps_ok": {n: step_ok(n) for n in required + ["push", "resolve_runtime"]},
        "evidence": evidence,
    }
    evidence_dir = os.path.join(
        os.path.dirname(ROOT),
        "var",
        "evidence",
    )
    os.makedirs(evidence_dir, exist_ok=True)
    artifact_path = os.path.join(evidence_dir, f"{run_id}.json")
    with open(artifact_path, "w", encoding="utf-8") as fh:
        json.dump({"summary": out, "steps": steps}, fh, indent=2, default=str)
    out["artifact_path"] = artifact_path
    print(json.dumps(out, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
