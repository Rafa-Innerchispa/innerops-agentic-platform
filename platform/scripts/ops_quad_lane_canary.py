#!/usr/bin/env python3
"""Canary barato: 4 ops tasks (dev_swarm + cursor + codex + antigravity) mismo objetivo, comparar SHA256.

Fase por defecto (--mode orchestrate): crea tareas, autoriza, claim+complete sin LLM (evidencia = hash real del repo).
Fase --mode create-only: solo admite y reporta binding / list_claimable (0 ejecución).

v4 (post canary v3): authorize+claim de TODOS los lanes interactivos primero
(ningún lane muere de inanición tras un wait ajeno); waits incluyen los
gates verification/pending_human_review (sin waits fútiles de 300s); la
extracción de evidencia recorre formas anidadas (agent_result, gate); el
match de SHAs exige evidencia en los 4 lanes (el match vicioso 1/4 = False).
Lane ok = completed con evidencia, o verification con evidencia que coincide
con el SHA compartido (flow probado; terminal `completed` requiere approve
humano por diseño fail-closed).
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
    base = Path(
        str(
            inspected.get("source_path")
            or inspected.get("path")
            or inspected.get("repo_path")
            or ROOT
        )
    )
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
        payload = {"canary_test_type": "git_head_only", "suppress_owner_whatsapp_auth": True} if lane_name == "dev_swarm" else {"suppress_owner_whatsapp_auth": True}
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
            payload=payload,
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


def _git_head(path: str) -> str:
    import subprocess

    proc = subprocess.run(
        ["git", "-C", path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "rev-parse failed")
    return proc.stdout.strip()


def extract_evidence_sha(final: dict[str, Any]) -> str | None:
    """Best-effort commit_sha across evidence shapes (flat + nested).

    Interactive completions store candidate_evidence.commit_sha; autonomous
    (dev_swarm) completions nest it under evidence.agent_result(.evidence)
    or evidence.gate_verification. First non-empty hit wins.
    """
    final = final or {}
    cands: list[Any] = [
        (final.get("candidate_evidence") or {}).get("commit_sha"),
        (final.get("evidence") or {}).get("commit_sha"),
    ]
    agent = (final.get("evidence") or {}).get("agent_result") or {}
    cands.append(agent.get("commit_sha"))
    cands.append((agent.get("evidence") or {}).get("commit_sha"))
    cands.append(((final.get("evidence") or {}).get("gate_verification") or {}).get("commit_sha"))
    for cand in cands:
        if cand:
            return str(cand)
    return None


def evidence_shas_match(lanes: list[dict[str, Any]]) -> tuple[bool, Any]:
    """Strict cross-lane SHA agreement: every lane must evidence, all equal.

    A single evidencing lane out of four is NOT a match (canary v3 flaw).
    Returns (match, shared_sha_or_sorted_list).
    """
    shas = [r.get("evidence_commit") for r in (lanes or [])]
    present = [s for s in shas if s]
    if not lanes or len(present) != len(shas):
        return False, sorted(set(present))
    uniq = set(present)
    if len(uniq) == 1:
        return True, present[0]
    return False, sorted(uniq)


def _interactive_claim(provider: str, task_id: str) -> dict[str, Any]:
    from inneros_core_runtime import interactive_ops_runner as ior

    ior.authorize_ops_task(provider, task_id, owner_actor="RAFAEL", channel="quad_canary")
    return ior.claim_ops_task(provider, task_id=task_id, owner_approved=True)


def _interactive_finish(
    provider: str, task_id: str, claim: dict[str, Any], *, fallback_sha: str, repo_path: str
) -> dict[str, Any]:
    from inneros_core_runtime import interactive_ops_runner as ior

    if not (claim or {}).get("ok"):
        return {"ok": False, "stage": "claim", "claim": claim}
    wt = str(claim.get("worktree") or repo_path)
    commit_sha = _git_head(wt)
    evidence = {"commit_sha": commit_sha, "notes": f"read-only rev-parse @ {wt}", "reference_fallback": fallback_sha}
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

    def _created_task_id(create: dict[str, Any]) -> str:
        return str(create.get("task_id") or (create.get("task") or {}).get("task_id") or "")

    # Phase A: authorize+claim EVERY interactive lane up front. A lane must
    # never starve behind another lane's completion wait (canary v3: codex
    # and antigravity were circuit-broken before their sequential turn).
    early_claims: dict[str, dict[str, Any]] = {}
    for entry in created_lanes:
        lane = entry["lane"]
        if lane == "dev_swarm":
            continue
        create = entry.get("create") or {}
        task_id = _created_task_id(create) if create.get("ok") else ""
        if not task_id:
            continue
        try:
            early_claims[lane] = _interactive_claim(lane, task_id)
        except Exception as exc:  # canary always emits a JSON verdict
            early_claims[lane] = {"ok": False, "error": "claim_exception", "detail": str(exc)[:200]}

    for entry in created_lanes:
        lane = entry["lane"]
        create = entry.get("create") or {}
        if not create.get("ok"):
            report["lanes"].append({"lane": lane, "ok": False, "terminal": False,
                                     "error": "create_failed", "create": create})
            continue
        task_id = _created_task_id(create)
        if not task_id:
            report["lanes"].append({"lane": lane, "ok": False, "terminal": False,
                                     "error": "task_id_missing", "create": create})
            continue

        lane_result: dict[str, Any] = {"lane": lane, "task_id": task_id}

        if lane == "dev_swarm":
            final = _wait_status(task_id, want={"completed", "failed", "blocked", "cancelled"}, timeout_s=300)
            lane_result["final_status"] = final.get("status")
            lane_result["evidence_commit"] = extract_evidence_sha(final)
        else:
            lane_result["claimable_before"] = _report_claimable(correlation_id).get(lane)
            claim = early_claims.get(lane) or {"ok": False, "error": "claim_skipped"}
            try:
                fin = _interactive_finish(lane, task_id, claim, fallback_sha=head_sha, repo_path=repo_path)
            except Exception as exc:  # canary always emits a JSON verdict
                fin = {"ok": False, "stage": "exception", "error": str(exc)[:200], "claim": claim}
            lane_result["interactive"] = fin
            final = _wait_status(task_id, want={"completed", "failed", "verification",
                                                "pending_human_review"}, timeout_s=300)
            lane_result["final_status"] = final.get("status")
            lane_result["evidence_commit"] = extract_evidence_sha(final)

        report["lanes"].append(lane_result)

    # Pass 2: strict SHA agreement first, then per-lane verdicts. Interactive
    # verification with matching evidence = flow proven (terminal `completed`
    # needs a human approve by fail-closed design); anything else must be
    # completed with evidence. pending_human_review is never ok (breaker).
    match, shared = evidence_shas_match(report["lanes"])
    for lane_result in report["lanes"]:
        if lane_result.get("error"):
            continue
        status = lane_result.get("final_status")
        ev = lane_result.get("evidence_commit")
        lane_result["terminal"] = status == "completed"
        if lane_result["lane"] == "dev_swarm":
            lane_result["ok"] = (status == "completed") and bool(ev)
        else:
            lane_result["ok"] = bool(ev) and (
                status == "completed" or (status == "verification" and match and ev == shared)
            )

    report["all_evidence_shas_match"] = match
    report["shared_commit_sha"] = shared
    report["all_lanes_ok"] = all(r.get("ok") for r in report["lanes"])
    report["all_terminal"] = all(r.get("terminal") for r in report["lanes"])
    report["ok"] = report["all_lanes_ok"]
    report["finished_at"] = _utc()
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
