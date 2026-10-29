"""Cierra canaries read-only (git rev-parse) tras claim — sin LLM ni IDE."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime import execution_receipts as receipts
from inneros_core_runtime import interactive_ops_runner as ior
from inneros_core_runtime import racb_protocol as racb
from pathlib import Path


def _is_readonly_verification(task: dict[str, Any]) -> bool:
    if str(task.get("task_class") or "") != "verification":
        return False
    objective = str(task.get("objective") or task.get("title") or "").lower()
    return "rev-parse" in objective or "commit_sha" in objective


def _git_head(path: str) -> str:
    proc = subprocess.run(
        ["git", "-C", path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "rev-parse failed")
    return proc.stdout.strip()


def try_finish_verification_task(
    *,
    task_id: str,
    provider: str | None = None,
    owner_actor: str = "RAFAEL",
) -> dict[str, Any] | None:
    """Si la ops task está claimed y es canary rev-parse, completa con SHA real."""
    tid = (task_id or "").strip()
    if not tid:
        return None
    task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if not task:
        return {"ok": False, "task_id": tid, "error": "task_not_found"}
    if not _is_readonly_verification(task):
        return None
    status = str(task.get("status") or "").lower()
    if status in {"completed", "failed", "cancelled", "superseded"}:
        return {"ok": False, "task_id": tid, "skipped": f"terminal:{status}"}
    prov = ior.normalize_provider(provider or task.get("preferred_provider") or task.get("assignee"))
    claim_token = str(task.get("claim_token") or "")
    worktree = str(task.get("worktree") or task.get("claim_worktree") or "").strip()
    if status not in {"claimed", "running", "verification"}:
        if status.startswith("awaiting_"):
            return {"ok": False, "task_id": tid, "skipped": "not_claimed_yet", "status": status}
        return {"ok": False, "task_id": tid, "skipped": f"status:{status}"}
    if not claim_token:
        return {"ok": False, "task_id": tid, "error": "missing_claim_token"}
    if not worktree:
        claim = task.get("claim") or {}
        if isinstance(claim, dict):
            worktree = str(claim.get("worktree") or "").strip()
    if not worktree:
        return {"ok": False, "task_id": tid, "error": "missing_worktree"}

    sha = _git_head(worktree)
    pin = ior.pinned_model(prov)
    if pin:
        mongo_store.get_db()[OPS_TASKS_COL].update_one(
            {"task_id": tid},
            {
                "$set": {
                    "preferred_model": pin,
                    "effective_model": pin,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
    out = ior.complete_ops_task(
        prov,
        tid,
        claim_token=claim_token,
        status="completed",
        evidence={
            "commit_sha": sha,
            "notes": "ops_verification_autofinish: read-only rev-parse (0 créditos LLM)",
            "owner_actor": owner_actor,
        },
    )
    return {"ok": bool(out.get("ok")), "task_id": tid, "provider": prov, "complete": out, "commit_sha": sha}


def try_fail_verification_no_new_commit(
    *,
    task_id: str,
    superseded_by: str | None = None,
) -> dict[str, Any] | None:
    """Close verification tasks that cannot produce a task-scoped commit receipt."""
    tid = (task_id or "").strip()
    if not tid:
        return None
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if not task:
        return {"ok": False, "task_id": tid, "error": "task_not_found"}
    status = str(task.get("status") or "").lower()
    if status != "verification":
        if status == "failed" and task.get("reconcile_note") == "verification_failed_no_new_commit_for_task":
            return {"ok": True, "task_id": tid, "skipped": "already_reconciled_failed"}
        if status == "completed":
            return {"ok": True, "task_id": tid, "skipped": "already_completed"}
        return {"ok": False, "task_id": tid, "skipped": f"status:{status}"}
    worktree_raw = str(task.get("worktree") or task.get("local_worktree") or "").strip()
    if not worktree_raw:
        return {"ok": False, "task_id": tid, "error": "missing_worktree"}
    worktree = Path(worktree_raw).expanduser()
    before_sha = str(task.get("git_baseline_sha") or receipts.git_head(worktree)).strip()
    proof = receipts.committed_objective_receipt(worktree, before_sha)
    if proof.get("ok"):
        return {"ok": False, "task_id": tid, "skipped": "receipt_ok"}
    if proof.get("error") != "no_new_commit_for_task":
        return {"ok": False, "task_id": tid, "skipped": proof.get("error"), "receipt": proof}

    evidence = {
        "status": "FAILED",
        "result": "no_new_commit_for_task",
        "receipt": proof,
        "notes": "verification closed: repair landed on main without task-scoped commit",
    }
    transition = racb.build_transition(
        current_status=status,
        target_status="failed",
        current_revision=int(task.get("revision") or 0),
        actor="ops_verification_autofinish",
        evidence=evidence,
    )
    if not transition.get("ok"):
        return {"ok": False, "task_id": tid, "error": transition.get("error"), "receipt": proof}
    patch = {
        **(transition.get("patch") or {}),
        "reconcile_note": "verification_failed_no_new_commit_for_task",
        "reconcile_evidence": {
            "receipt": proof,
            "superseded_by": superseded_by,
            "github_main_sha_at_close": receipts.git_head(worktree),
        },
        "last_error": "no_new_commit_for_task",
    }
    if superseded_by:
        patch["superseded_by"] = superseded_by
    filt: dict[str, Any] = {"task_id": tid, "status": "verification"}
    if "revision" in task:
        filt["revision"] = task["revision"]
    change = db[OPS_TASKS_COL].update_one(filt, {"$set": patch})
    if getattr(change, "modified_count", 0) != 1:
        return {"ok": False, "task_id": tid, "error": "concurrent_update", "receipt": proof}
    return {"ok": True, "task_id": tid, "status": "failed", "receipt": proof}


def run_autofinish_batch(*, limit: int = 10) -> dict[str, Any]:
    db = mongo_store.get_db()
    rows = list(
        db[OPS_TASKS_COL]
        .find(
            {
                "task_class": "verification",
                "status": {"$in": ["claimed", "running", "verification"]},
                "objective": {"$regex": "rev-parse", "$options": "i"},
            },
            {"_id": 0, "task_id": 1, "preferred_provider": 1, "assignee": 1},
        )
        .sort("updated_at", -1)
        .limit(max(1, min(limit, 30)))
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        tid = str(row.get("task_id") or "")
        prov = row.get("preferred_provider") or row.get("assignee")
        r = try_finish_verification_task(task_id=tid, provider=str(prov or ""))
        if r:
            results.append(r)
    ok_count = sum(1 for r in results if r.get("ok"))
    return {"ok": True, "processed": len(results), "completed": ok_count, "results": results}
