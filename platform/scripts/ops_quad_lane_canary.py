#!/usr/bin/env python3
"""Canary barato: 4 ops tasks (dev_swarm + cursor + codex + antigravity) mismo objetivo, comparar SHA256.

Fase por defecto (--mode orchestrate): crea tareas, autoriza, claim+complete sin LLM (evidencia = hash real del repo).
Fase --mode create-only: solo admite y reporta binding / list_claimable (0 ejecución).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_REPO = "Rafa-Innerchispa/innerops-agentic-platform"
OBJECTIVE = (
    "Solo lectura: en el worktree ejecuta git rev-parse HEAD y entrega commit_sha en evidencia. "
    "Prohibido modificar archivos, commits o push."
)

LANES: list[tuple[str, str, str]] = [
    ("dev_swarm", "dev_swarm", "local_dev_swarm"),
    ("cursor", "cursor", "cursor_interactive"),
    ("codex", "codex", "codex_interactive"),
    ("antigravity", "antigravity", "antigravity_interactive"),
]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reference_head_sha(repo_slug: str) -> tuple[str, str]:
    import subprocess

    from inneros_core_runtime import local_execution_plane as lep

    inspected = lep.inspect_repo(repo_slug)
    base = Path(str(inspected.get("path") or inspected.get("repo_path") or ROOT))
    if not (base / ".git").exists() and (ROOT / ".git").exists():
        base = ROOT
    proc = subprocess.run(
        ["git", "-C", str(base), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {proc.stderr.strip()}")
    return proc.stdout.strip(), str(base)


def _create_quad(*, correlation_id: str, repo: str, dry: bool) -> list[dict[str, Any]]:
    from inneros_core_runtime import coordination_live as cl
    from inneros_core_runtime import execution_binding as eb

    out: list[dict[str, Any]] = []
    for lane_name, provider, exec_lane in LANES:
        idem = f"{correlation_id}|{lane_name}"
        title = f"[quad-canary] {lane_name} SHA256 AGENTS.md"
        if dry:
            binding = eb.resolve_execution_binding(
                {
                    "preferred_provider": provider,
                    "assignee": provider,
                    "execution_lane": exec_lane,
                    "repo": repo,
                    "do_not_auto_dispatch": provider != "dev_swarm",
                    "objective": OBJECTIVE,
                }
            )
            out.append({"lane": lane_name, "dry_run": True, "binding": binding})
            continue
        created = cl.create_ops_task(
            assignee=provider,
            title=title,
            correlation_id=correlation_id,
            repo=repo,
            objective=OBJECTIVE,
            task_class="verification",
            execution_lane=exec_lane,
            preferred_provider=provider,
            do_not_auto_dispatch=provider != "dev_swarm",
            idempotency_key=idem,
            evidence_required=["commit_sha"],
            from_agent="ops_quad_lane_canary",
        )
        binding = eb.resolve_execution_binding({**created.get("task", created), "objective": OBJECTIVE})
        out.append({"lane": lane_name, "create": created, "binding": binding})
    return out


def _wait_status(task_id: str, *, want: set[str], timeout_s: int = 120) -> dict[str, Any]:
    from raphiia_openai import mongo_store
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL

    db = mongo_store.get_db()
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or {}
        if str(last.get("status") or "") in want:
            return last
        time.sleep(2)
    return last


def _interactive_finish(provider: str, task_id: str, *, commit_sha: str, repo_path: str) -> dict[str, Any]:
    from inneros_core_runtime import interactive_ops_runner as ior

    ior.authorize_ops_task(provider, task_id, owner_actor="RAFAEL", channel="quad_canary")
    claim = ior.claim_ops_task(provider, task_id=task_id, owner_approved=True)
    if not claim.get("ok"):
        return {"ok": False, "stage": "claim", "claim": claim}
    evidence = {"commit_sha": commit_sha, "notes": f"read-only rev-parse @ {repo_path}"}
    done = ior.complete_ops_task(
        provider,
        task_id,
        claim_token=str(claim.get("claim_token") or ""),
        status="completed",
        evidence=evidence,
    )
    return {"ok": bool(done.get("ok")), "claim": claim, "complete": done}


def _report_claimable(correlation_id: str) -> dict[str, Any]:
    from inneros_core_runtime import interactive_ops_runner as ior

    rep: dict[str, Any] = {}
    for prov in ("cursor", "codex", "antigravity"):
        rep[prov] = ior.list_claimable_ops_tasks(provider=prov, limit=5, correlation_id=correlation_id)
    return rep


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--correlation-id", default="")
    parser.add_argument("--mode", choices=("create-only", "orchestrate"), default="orchestrate")
    parser.add_argument("--dry-run", action="store_true", help="Solo binding, no Mongo/Temporal")
    args = parser.parse_args()

    correlation_id = args.correlation_id.strip() or f"quad-lane-canary-{uuid.uuid4().hex[:10]}"
    head_sha, repo_path = _reference_head_sha(args.repo)

    report: dict[str, Any] = {
        "ok": True,
        "correlation_id": correlation_id,
        "repo": args.repo,
        "reference_commit_sha": head_sha,
        "reference_repo_path": repo_path,
        "started_at": _utc(),
        "mode": args.mode,
        "lanes": [],
    }

    created_lanes = _create_quad(correlation_id=correlation_id, repo=args.repo, dry=args.dry_run)
    report["create_phase"] = created_lanes

    if args.dry_run or args.mode == "create-only":
        report["claimable"] = {} if args.dry_run else _report_claimable(correlation_id)
        report["finished_at"] = _utc()
        print(json.dumps(report, indent=2, default=str))
        return 0

    for entry in created_lanes:
        lane = entry["lane"]
        create = entry.get("create") or {}
        if not create.get("ok"):
            report["lanes"].append({"lane": lane, "ok": False, "error": "create_failed", "create": create})
            continue
        task_id = str(create.get("task_id") or (create.get("task") or {}).get("task_id") or "")
        if not task_id:
            report["lanes"].append({"lane": lane, "ok": False, "error": "task_id_missing", "create": create})
            continue

        lane_result: dict[str, Any] = {"lane": lane, "task_id": task_id}

        if lane == "dev_swarm":
            final = _wait_status(task_id, want={"completed", "failed", "blocked", "cancelled"}, timeout_s=180)
            lane_result["final_status"] = final.get("status")
            ev = final.get("candidate_evidence") or final.get("evidence") or {}
            lane_result["evidence_commit"] = ev.get("commit_sha")
            lane_result["ok"] = final.get("status") == "completed" and lane_result["evidence_commit"] == head_sha
        else:
            lane_result["claimable_before"] = _report_claimable(correlation_id).get(lane)
            fin = _interactive_finish(lane, task_id, commit_sha=head_sha, repo_path=repo_path)
            lane_result["interactive"] = fin
            final = _wait_status(task_id, want={"completed", "verification", "failed"}, timeout_s=120)
            lane_result["final_status"] = final.get("status")
            ev = final.get("candidate_evidence") or {}
            lane_result["evidence_commit"] = ev.get("commit_sha")
            lane_result["ok"] = final.get("status") == "completed" and lane_result.get("evidence_commit") == head_sha

        report["lanes"].append(lane_result)

    shas = {r.get("evidence_commit") for r in report["lanes"] if r.get("evidence_commit")}
    report["all_sha_match_reference"] = shas == {head_sha} and len(report["lanes"]) == 4
    report["all_lanes_ok"] = all(r.get("ok") for r in report["lanes"])
    report["ok"] = report["all_lanes_ok"]
    report["finished_at"] = _utc()
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
