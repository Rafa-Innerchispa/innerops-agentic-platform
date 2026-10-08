"""Codex interactive ops — claim/complete vía Temporal (sin runner internal genérico)."""

from __future__ import annotations

import os
import secrets
import socket
from datetime import datetime, timezone, timedelta
from typing import Any

from raphiia_openai import mongo_store

from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime.coordination_live import OPS_TASKS_COL, _publish_task_event, heartbeat_ops_task
from inneros_core_runtime.cursor_ops_runner import (
    _evidence_to_agent_result,
    _lease_valid,
    _release_claim,
    _validate_completion_evidence,
)

CODEX_PINNED_MODEL = os.getenv("CODEX_OPS_PINNED_MODEL", os.getenv("CODEX_WHATSAPP_MODEL", "gpt-5.6-sol")).strip()
LEASE_SECONDS = int(os.getenv("CODEX_OPS_LEASE_SECONDS", "3600"))
CLAIM_STATUSES = frozenset(
    {
        "queued",
        "waiting_for_binding",
        "awaiting_codex_claim",
        "awaiting_cursor_claim",
        "waiting_for_model_binding",
        "blocked",
        "failed",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_until() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).isoformat()


def _host() -> str:
    return socket.gethostname()


def _validate_pinned_model(*, task: dict[str, Any] | None = None) -> dict[str, Any] | None:
    expected = CODEX_PINNED_MODEL.strip()
    if not expected:
        return {"ok": False, "error": "CODEX_OPS_PINNED_MODEL_unset"}
    for field in ("preferred_model", "effective_model"):
        val = str((task or {}).get(field) or "").strip()
        if val and val != expected:
            return {"ok": False, "error": "model_not_pinned", "expected": expected, "got": val}
    return None


def _codex_agent_result(evidence: dict[str, Any], *, status: str) -> dict[str, Any]:
    base = _evidence_to_agent_result(evidence, status=status)
    base["completion_channel"] = "codex_interactive"
    base["codex_completion_status"] = status
    return base


def list_claimable_ops_tasks(*, limit: int = 10, correlation_id: str | None = None) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {
        "$or": [{"status": {"$in": sorted(CLAIM_STATUSES)}}, {"status": "running", "assignee": "codex", "claim_token": {"$exists": False}}],
        "$and": [{"$or": [{"assignee": "codex"}, {"preferred_provider": "codex"}]}],
    }
    if correlation_id:
        filt["correlation_id"] = correlation_id.strip()
    rows = list(db[OPS_TASKS_COL].find(filt, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 50))))
    return {
        "ok": True,
        "count": len(rows),
        "pinned_model": CODEX_PINNED_MODEL,
        "tasks": [
            {
                "task_id": t.get("task_id"),
                "title": t.get("title"),
                "status": t.get("status"),
                "correlation_id": t.get("correlation_id"),
                "repo": t.get("repo"),
                "work_branch": t.get("work_branch"),
                "owner_authorized": bool(t.get("owner_authorized_at")),
            }
            for t in rows
        ],
    }


def authorize_ops_task_for_codex(
    task_id: str,
    *,
    owner_actor: str = "RAFAEL",
    channel: str = "explicit",
) -> dict[str, Any]:
    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    db = mongo_store.get_db()
    now = _now()
    doc = db[OPS_TASKS_COL].find_one_and_update(
        {"task_id": tid},
        {
            "$set": {
                "owner_authorized_at": now,
                "owner_authorized_by": owner_actor,
                "owner_authorization_channel": channel,
                "updated_at": now,
            }
        },
        return_document=True,
    )
    if not doc:
        return {"ok": False, "error": "task_not_found", "task_id": tid}
    return {"ok": True, "task_id": tid, "owner_authorized_at": now}


def claim_ops_task(
    *,
    task_id: str | None = None,
    correlation_id: str | None = None,
    owner_approved: bool = False,
    owner_actor: str = "RAFAEL",
) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {
        "$or": [{"status": {"$in": sorted(CLAIM_STATUSES)}}, {"status": "running", "assignee": "codex", "claim_token": {"$exists": False}}],
        "$and": [{"$or": [{"assignee": "codex"}, {"preferred_provider": "codex"}]}],
    }
    if task_id:
        filt = {"task_id": task_id.strip(), **filt}
    elif correlation_id:
        filt["correlation_id"] = correlation_id.strip()
    task = db[OPS_TASKS_COL].find_one(filt, sort=[("created_at", -1)])
    if not task:
        return {"ok": False, "error": "no_claimable_task"}
    tid = str(task.get("task_id") or "")
    if not (bool(task.get("owner_authorized_at")) or owner_approved):
        return {"ok": False, "error": "owner_approval_required", "task_id": tid}
    token = secrets.token_hex(8)
    now = _now()
    claimed = db[OPS_TASKS_COL].find_one_and_update(
        {"task_id": tid, "$or": [{"status": {"$in": sorted(CLAIM_STATUSES)}}, {"status": "running", "assignee": "codex", "claim_token": {"$exists": False}}]},
        {
            "$set": {
                "status": "claimed",
                "claimed_at": now,
                "claimed_by": "codex",
                "claim_token": token,
                "claim_host": _host(),
                "lease_until": _lease_until(),
                "execution_lane": "codex_interactive",
                "preferred_provider": "codex",
                "preferred_model": CODEX_PINNED_MODEL,
                "effective_model": CODEX_PINNED_MODEL,
                "runner": "codex_interactive",
                "updated_at": now,
            },
            "$inc": {"revision": 1},
        },
        return_document=True,
    )
    if not claimed:
        return {"ok": False, "error": "claim_conflict", "task_id": tid}
    model_err = _validate_pinned_model(task=claimed)
    if model_err:
        _release_claim(db, tid, reason=str(model_err.get("error")))
        return {**model_err, "task_id": tid}
    worktree_path = ""
    repo = str(claimed.get("repo") or "").strip()
    if repo:
        from inneros_core_runtime import local_execution_plane as lep

        wt = lep.create_worktree(
            repo=repo,
            base_branch=str(claimed.get("base_ref") or "main"),
            work_branch=str(claimed.get("work_branch") or f"codex/ops-{tid.replace('ops_', '')}"),
            actor="codex",
            task_id=tid,
            correlation_id=str(claimed.get("correlation_id") or tid),
            idempotency_key=f"codex-claim-{tid}",
        )
        if wt.get("ok"):
            worktree_path = str(wt.get("worktree") or "")
        if not worktree_path:
            _release_claim(db, tid, reason="worktree_create_failed")
            return {"ok": False, "error": "worktree_required", "task_id": tid, "details": wt}
        db[OPS_TASKS_COL].update_one({"task_id": tid, "claim_token": token}, {"$set": {"worktree": worktree_path}})
    from inneros_core_runtime import durable_coordination_spine

    handoff = durable_coordination_spine.signal_task_workflow(
        tid,
        "cursor_claim_handoff",
        {
            "claim_token": token,
            "status": "claimed",
            "preferred_provider": "codex",
            "preferred_model": CODEX_PINNED_MODEL,
            "effective_model": CODEX_PINNED_MODEL,
            "worktree": worktree_path,
        },
    )
    heartbeat_ops_task(tid, actor="codex", phase="claimed", current_step="codex_interactive", last_progress=f"Codex claim {_host()}")
    binding = eb.resolve_execution_binding({**claimed, "owner_approved": True})
    return {
        "ok": True,
        "task_id": tid,
        "claim_token": token,
        "pinned_model": CODEX_PINNED_MODEL,
        "worktree": worktree_path,
        "temporal_handoff": handoff,
        "execution_binding": binding,
    }


def complete_ops_task(
    task_id: str,
    *,
    claim_token: str,
    status: str = "completed",
    evidence: dict[str, Any] | None = None,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    tid = (task_id or "").strip()
    tok = (claim_token or "").strip()
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid, "claim_token": tok, "assignee": "codex"})
    if not task:
        return {"ok": False, "error": "claim_token_mismatch_or_task_missing", "task_id": tid}
    if not _lease_valid(task):
        return {"ok": False, "error": "lease_expired", "task_id": tid}
    model_err = _validate_pinned_model(task=task)
    if model_err:
        return {**model_err, "task_id": tid}
    normalized = (status or "completed").strip().lower()
    ev = dict(evidence or {})
    if commit_sha:
        ev["commit_sha"] = commit_sha.strip()
    ev_err = _validate_completion_evidence(normalized, ev)
    if ev_err:
        return {"ok": False, "error": ev_err, "task_id": tid}
    agent_result = _codex_agent_result(ev, status=normalized)
    from inneros_core_runtime import durable_coordination_spine

    temporal = durable_coordination_spine.signal_task_workflow(
        tid,
        "cursor_execution_complete",
        {"submitted": True, "status": normalized, "agent_result": agent_result, "evidence": ev, "claim_token": tok},
    )
    if not temporal.get("ok"):
        return {"ok": False, "error": "temporal_completion_signal_failed", "details": temporal, "task_id": tid}
    now = _now()
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid, "claim_token": tok},
        {"$set": {"status": "verification", "updated_at": now, "candidate_evidence": ev}, "$inc": {"revision": 1}},
    )
    return {"ok": True, "task_id": tid, "status": "verification", "temporal": temporal, "evidence": ev}
