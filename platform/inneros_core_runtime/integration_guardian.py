"""Independent Integration Guardian for Dev Swarm verification results."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from raphiia_openai import coordination_live, local_execution_plane, mongo_store

WORKERS_COL = "ralfia_dev_swarm_workers"
SAFE_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


def _worktree(worker: dict[str, Any]) -> str:
    launch = worker.get("launch") if isinstance(worker.get("launch"), dict) else {}
    wt = launch.get("worktree") if isinstance(launch.get("worktree"), dict) else {}
    return str(wt.get("worktree") or "")


def _commit_head(worker: dict[str, Any]) -> str:
    executor = worker.get("executor") if isinstance(worker.get("executor"), dict) else {}
    commit = executor.get("commit") if isinstance(executor.get("commit"), dict) else {}
    return str(commit.get("head") or executor.get("commit_head") or "").strip()


def _launch_plan(worker: dict[str, Any]) -> dict[str, Any]:
    launch = worker.get("launch") if isinstance(worker.get("launch"), dict) else {}
    return launch.get("plan") if isinstance(launch.get("plan"), dict) else {}


def _canonical_target(worker: dict[str, Any]) -> str:
    """Return the durable branch that must contain the tested commit.

    Normal product work converges to ``main``. An explicit ``hackathon/*``
    target remains the contest-only delta and is never silently promoted to
    product main by this guardian.
    """
    plan = _launch_plan(worker)
    value = str(plan.get("requested_base_ref") or "main").strip()
    if value.startswith("refs/heads/"):
        value = value[len("refs/heads/") :]
    if value.startswith("origin/"):
        value = value[len("origin/") :]
    if not value or re.fullmatch(r"[a-fA-F0-9]{7,40}", value):
        value = "main"
    if not SAFE_TARGET_RE.fullmatch(value) or ".." in value or "@{" in value or value.startswith("-"):
        return "main"
    if value == "main" or value.startswith("hackathon/"):
        return value
    # Feature/review branches are temporary work, not durable product truth.
    return "main"


def _git(worktree: Path, args: list[str], timeout_seconds: int = 60) -> dict[str, Any]:
    return local_execution_plane._run(["git", *args], worktree, timeout_seconds=timeout_seconds)


def _is_ancestor(worktree: Path, ancestor: str, descendant: str) -> bool:
    result = _git(worktree, ["merge-base", "--is-ancestor", ancestor, descendant], timeout_seconds=30)
    return bool(result.get("ok"))


def _integration_gate(worker: dict[str, Any], expected_head: str) -> dict[str, Any]:
    """Fail closed until the tested commit is in canonical Git.

    The only automatic mutation is a non-force fast-forward push to the
    canonical target. Concurrent/divergent history, a dirty worktree or branch
    protection leaves the task in verification instead of declaring it done.
    """
    worktree_raw = _worktree(worker)
    if not worktree_raw or not expected_head:
        return {"ok": False, "status": "integration_pending", "reason": "integration_metadata_missing"}
    worktree = Path(worktree_raw)
    if not worktree.exists():
        return {"ok": False, "status": "integration_pending", "reason": "worktree_not_found"}

    target = _canonical_target(worker)
    remote_ref = f"origin/{target}"
    target_type = "hackathon" if target.startswith("hackathon/") else "product"
    evidence: dict[str, Any] = {
        "target": target,
        "target_type": target_type,
        "expected_head": expected_head,
        "auto_promotes_to_main": target == "main",
        "force_push": False,
    }

    fetch = _git(worktree, ["fetch", "origin", target], timeout_seconds=120)
    evidence["fetch_ok"] = bool(fetch.get("ok"))
    if not fetch.get("ok"):
        return {**evidence, "ok": False, "status": "integration_pending", "reason": "canonical_target_fetch_failed"}

    remote_head = _git(worktree, ["rev-parse", "--verify", f"{remote_ref}^{{commit}}"], timeout_seconds=30)
    remote_sha = str(remote_head.get("stdout") or "").strip()
    evidence["remote_before"] = remote_sha
    if not remote_head.get("ok") or not remote_sha:
        return {**evidence, "ok": False, "status": "integration_pending", "reason": "canonical_target_unresolved"}

    if _is_ancestor(worktree, expected_head, remote_ref):
        evidence["already_integrated"] = True
        evidence["remote_after"] = remote_sha
        return {**evidence, "ok": True, "status": "integrated", "reason": "tested_commit_already_in_canonical_target"}

    status = _git(worktree, ["status", "--porcelain"], timeout_seconds=30)
    dirty = bool(str(status.get("stdout") or "").strip()) or not status.get("ok")
    evidence["worktree_clean"] = not dirty
    if dirty:
        return {**evidence, "ok": False, "status": "integration_pending", "reason": "worktree_dirty_after_verification"}

    fast_forward = _is_ancestor(worktree, remote_ref, expected_head)
    evidence["fast_forward_possible"] = fast_forward
    if not fast_forward:
        return {**evidence, "ok": False, "status": "merge_required", "reason": "canonical_target_advanced_or_diverged"}

    push = _git(worktree, ["push", "origin", f"{expected_head}:refs/heads/{target}"], timeout_seconds=120)
    evidence["push_ok"] = bool(push.get("ok"))
    if not push.get("ok"):
        return {**evidence, "ok": False, "status": "merge_required", "reason": "fast_forward_push_rejected"}

    refetch = _git(worktree, ["fetch", "origin", target], timeout_seconds=120)
    evidence["refetch_ok"] = bool(refetch.get("ok"))
    if not refetch.get("ok"):
        return {**evidence, "ok": False, "status": "integration_pending", "reason": "post_push_fetch_failed"}
    remote_after = _git(worktree, ["rev-parse", "--verify", f"{remote_ref}^{{commit}}"], timeout_seconds=30)
    remote_after_sha = str(remote_after.get("stdout") or "").strip()
    evidence["remote_after"] = remote_after_sha
    integrated = bool(remote_after.get("ok")) and bool(remote_after_sha) and _is_ancestor(worktree, expected_head, remote_ref)
    if not integrated:
        return {**evidence, "ok": False, "status": "integration_pending", "reason": "post_push_verification_failed"}
    return {**evidence, "ok": True, "status": "integrated", "reason": "canonical_target_fast_forwarded"}


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
        "canonical_target": _canonical_target(worker),
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
        integration: dict[str, Any] | None = None
        if verdict.get("ok") and not dry_run:
            integration = _integration_gate(worker, str(verdict.get("expected_head") or ""))
        checked.append({**verdict, "integration": integration})
        if dry_run:
            continue
        task_id = str(verdict.get("task_id") or "")
        if not task_id:
            continue
        evidence = {
            "status": (
                "PASS"
                if verdict["ok"] and integration and integration.get("ok")
                else ("INTEGRATION_PENDING" if verdict["ok"] else "FAIL")
            ),
            "guardian": "Integration Guardian",
            "guardian_independent": True,
            "verification": verdict,
            "integration": integration,
        }
        if verdict["ok"] and integration and integration.get("ok"):
            database[WORKERS_COL].update_one({"task_id": task_id}, {"$set": {
                "status": "executed",
                "guardian.status": "PASS",
                "guardian.evidence": evidence,
                "executor.final_status": "PASS",
                "executor.finalized_by": "integration_guardian",
            }})
            coordination_live.update_ops_task_state(task_id, "completed", actor="ralfia", evidence=evidence, force_handoff=True)
        elif verdict["ok"]:
            reason = str((integration or {}).get("reason") or "canonical_integration_pending")
            database[WORKERS_COL].update_one({"task_id": task_id}, {"$set": {
                "status": "verification",
                "guardian.status": "INTEGRATION_PENDING",
                "guardian.evidence": evidence,
                "blocker": reason,
                "executor.final_status": "INTEGRATION_PENDING",
                "executor.finalized_by": "integration_guardian",
            }})
            try:
                coordination_live.update_ops_task_state(
                    task_id,
                    "verification",
                    actor="ralfia",
                    evidence=evidence,
                    force_handoff=True,
                )
            except Exception:
                pass
            coordination_live.heartbeat_ops_task(
                task_id,
                "ralfia",
                next_action="Integrate the tested commit into the canonical target and rerun Integration Guardian",
                blocker=reason[:1000],
            )
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
        "ok": all(item.get("ok") and (dry_run or (item.get("integration") or {}).get("ok")) for item in checked) if checked else True,
        "guardian": "Integration Guardian",
        "checked": checked,
        "count": len(checked),
        "dry_run": dry_run,
    }
