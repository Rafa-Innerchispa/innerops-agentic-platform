"""After owner HA approval, finish bounded interactive ops without IDE session polling."""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

_REV_PARSE = re.compile(r"rev-parse|commit_sha", re.I)


def autopilot_enabled() -> bool:
    return os.getenv("OPS_POST_OWNER_AUTOPILOT", "1").strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_rev_parse_verification(task: dict[str, Any]) -> bool:
    if str(task.get("task_class") or "") == "verification":
        return True
    blob = " ".join(
        [
            str(task.get("objective") or ""),
            str(task.get("title") or ""),
            " ".join(str(x) for x in (task.get("evidence_required") or [])),
        ]
    )
    return bool(_REV_PARSE.search(blob))


def try_finish_after_owner_auth(task_id: str) -> dict[str, Any]:
    """Claim + rev-parse + complete for authorized Antigravity/Codex/Cursor verification ops."""
    if not autopilot_enabled():
        return {"ok": False, "skipped": "autopilot_disabled"}
    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}

    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from raphiia_openai import mongo_store

    task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid})
    if not task:
        return {"ok": False, "error": "task_not_found"}
    if not task.get("owner_authorized_at"):
        return {"ok": False, "skipped": "not_owner_authorized"}
    if str(task.get("status") or "") in {"completed", "failed", "cancelled", "superseded", "archived"}:
        return {"ok": True, "skipped": "already_terminal", "status": task.get("status")}
    if not _looks_like_rev_parse_verification(task):
        return {"ok": False, "skipped": "not_bounded_verification_autopilot"}

    provider = str(task.get("assignee") or task.get("preferred_provider") or "").lower()
    if provider == "antigravity":
        from inneros_core_runtime import antigravity_ops_runner as runner

        claim = runner.claim_ops_task(task_id=tid, owner_approved=True, owner_actor="OPS_AUTOPILOT")
        if not claim.get("ok"):
            return {"ok": False, "stage": "claim", "result": claim}
        wt = str(claim.get("worktree") or "").strip()
        if not wt:
            return {"ok": False, "stage": "claim", "error": "missing_worktree", "result": claim}
        proc = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"], capture_output=True, text=True)
        if proc.returncode != 0:
            runner.complete_ops_task(
                tid,
                claim_token=str(claim.get("claim_token") or ""),
                status="failed",
                evidence={"error": "rev_parse_failed", "stderr": proc.stderr[:500]},
            )
            return {"ok": False, "stage": "rev_parse", "stderr": proc.stderr[:300]}
        sha = proc.stdout.strip()
        done = runner.complete_ops_task(
            tid,
            claim_token=str(claim.get("claim_token") or ""),
            status="completed",
            evidence={"commit_sha": sha, "notes": "ops_post_owner_autopilot", "autopilot": True},
            commit_sha=sha,
        )
        return {"ok": bool(done.get("ok")), "stage": "complete", "provider": provider, "commit_sha": sha, "result": done}

    from inneros_core_runtime import interactive_ops_runner as ior

    claim = ior.claim_ops_task(provider, task_id=tid, owner_approved=True, owner_actor="OPS_AUTOPILOT")
    if not claim.get("ok"):
        return {"ok": False, "stage": "claim", "result": claim}
    wt = str(claim.get("worktree") or "").strip()
    proc = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"], capture_output=True, text=True)
    if proc.returncode != 0:
        ior.complete_ops_task(
            provider,
            tid,
            claim_token=str(claim.get("claim_token") or ""),
            status="failed",
            evidence={"error": "rev_parse_failed"},
        )
        return {"ok": False, "stage": "rev_parse"}
    sha = proc.stdout.strip()
    done = ior.complete_ops_task(
        provider,
        tid,
        claim_token=str(claim.get("claim_token") or ""),
        status="completed",
        evidence={"commit_sha": sha, "notes": "ops_post_owner_autopilot", "autopilot": True},
    )
    return {"ok": bool(done.get("ok")), "stage": "complete", "provider": provider, "commit_sha": sha, "result": done}
