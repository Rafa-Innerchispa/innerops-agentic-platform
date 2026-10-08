"""Cursor interactive ops runner — claim, execute, complete (Composer pinned)."""

from __future__ import annotations

import os
import secrets
import socket
from datetime import datetime, timezone, timedelta
from typing import Any

from raphiia_openai import mongo_store

from inneros_core_runtime import cursor_execution_plane as cep
from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime.coordination_live import OPS_TASKS_COL, _publish_task_event, heartbeat_ops_task

CURSOR_PINNED_MODEL = os.getenv("CURSOR_OPS_PINNED_MODEL", "composer-2.5-fast").strip()
LEASE_SECONDS = int(os.getenv("CURSOR_OPS_LEASE_SECONDS", "3600"))
CLAIM_STATUSES = frozenset(
    {
        "queued",
        "waiting_for_binding",
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


def list_claimable_ops_tasks(*, limit: int = 10, correlation_id: str | None = None) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {
        "$or": [
            {"status": {"$in": sorted(CLAIM_STATUSES)}},
            {
                "status": "running",
                "assignee": "cursor",
                "claim_token": {"$exists": False},
            },
        ],
        "$and": [
            {
                "$or": [
                    {"assignee": "cursor"},
                    {"assigned_to": "cursor"},
                    {"preferred_provider": "cursor"},
                    {"owner": "cursor"},
                ]
            }
        ],
    }
    if correlation_id:
        filt["correlation_id"] = correlation_id.strip()
    rows = list(db[OPS_TASKS_COL].find(filt, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 50))))
    return {
        "ok": True,
        "count": len(rows),
        "pinned_model": CURSOR_PINNED_MODEL,
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


def authorize_ops_task_for_cursor(
    task_id: str,
    *,
    owner_actor: str = "RAFAEL",
    channel: str = "explicit",
) -> dict[str, Any]:
    """Owner gate — call from WhatsApp/voz/UI before Cursor spends credits."""
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
    return {
        "ok": True,
        "task_id": tid,
        "owner_authorized_at": now,
        "message": "Autorizado. Cursor puede claim_ops_task con owner_approved=true.",
    }


def claim_ops_task(
    *,
    task_id: str | None = None,
    correlation_id: str | None = None,
    owner_approved: bool = False,
    owner_actor: str = "RAFAEL",
) -> dict[str, Any]:
    """Exclusive claim for active Cursor session (Composer model pinned)."""
    cep.register_session_heartbeat(
        host=_host(),
        source="cursor_ops_runner.claim",
        role="ops_executor",
    )
    classified = cep.classify_cursor_execution()
    if classified.get("execution_classification") not in {"partial", "headless_ready"}:
        return {
            "ok": False,
            "error": "cursor_session_not_ready",
            "classification": classified,
            "hint": "Abre sesión Cursor en el host o autoriza vía owner_approved tras WhatsApp.",
        }

    db = mongo_store.get_db()
    filt: dict[str, Any] = {
        "$or": [
            {"status": {"$in": sorted(CLAIM_STATUSES)}},
            {
                "status": "running",
                "assignee": "cursor",
                "claim_token": {"$exists": False},
            },
        ],
        "$and": [
            {
                "$or": [
                    {"assignee": "cursor"},
                    {"assigned_to": "cursor"},
                    {"preferred_provider": "cursor"},
                ]
            }
        ],
    }
    if task_id:
        filt = {"task_id": task_id.strip(), **filt}
    elif correlation_id:
        filt["correlation_id"] = correlation_id.strip()

    task = db[OPS_TASKS_COL].find_one(filt, sort=[("created_at", -1)])
    if not task:
        return {"ok": False, "error": "no_claimable_task", "filter": filt}

    tid = str(task.get("task_id") or "")
    authorized = bool(task.get("owner_authorized_at")) or bool(owner_approved)
    if not authorized:
        return {
            "ok": False,
            "error": "owner_approval_required",
            "task_id": tid,
            "title": task.get("title"),
            "hint": (
                "Autoriza con cursor_authorize_ops_task o claim con owner_approved=true "
                "(WhatsApp/voz cuando aplique)."
            ),
        }

    token = secrets.token_hex(8)
    now = _now()
    claim_filter: dict[str, Any] = {
        "task_id": tid,
        "$or": [
            {"status": {"$in": sorted(CLAIM_STATUSES)}},
            {"status": "running", "assignee": "cursor", "claim_token": {"$exists": False}},
        ],
    }
    claimed = db[OPS_TASKS_COL].find_one_and_update(
        claim_filter,
        {
            "$set": {
                "status": "claimed",
                "claimed_at": now,
                "claimed_by": "cursor",
                "claim_token": token,
                "claim_host": _host(),
                "lease_until": _lease_until(),
                "execution_lane": "cursor_interactive",
                "preferred_provider": "cursor",
                "preferred_model": CURSOR_PINNED_MODEL,
                "effective_model": CURSOR_PINNED_MODEL,
                "runner": "cursor_interactive",
                "updated_at": now,
                "owner_authorized_at": task.get("owner_authorized_at") or now,
                "owner_authorized_by": task.get("owner_authorized_by") or owner_actor,
            },
            "$inc": {"revision": 1},
        },
        return_document=True,
    )
    if not claimed:
        return {"ok": False, "error": "claim_conflict", "task_id": tid}

    worktree_path = ""
    repo = str(claimed.get("repo") or "").strip()
    if repo:
        from inneros_core_runtime import local_execution_plane as lep

        branch = str(claimed.get("work_branch") or f"cursor/ops-{tid.replace('ops_', '')}")
        wt = lep.create_worktree(
            repo=repo,
            base_branch=str(claimed.get("base_ref") or "main"),
            work_branch=branch,
            actor="cursor",
            task_id=tid,
            correlation_id=str(claimed.get("correlation_id") or tid),
            idempotency_key=f"cursor-claim-{tid}",
        )
        if wt.get("ok"):
            worktree_path = str(wt.get("worktree") or "")

    _publish_task_event(
        "task.claimed",
        claimed,
        actor="cursor",
        status="claimed",
        payload={
            "claim_token": token,
            "host": _host(),
            "model": CURSOR_PINNED_MODEL,
            "worktree": worktree_path,
        },
    )
    heartbeat_ops_task(
        tid,
        actor="cursor",
        phase="claimed",
        current_step="cursor_interactive",
        last_progress=f"Claimed on {_host()} model={CURSOR_PINNED_MODEL}",
    )

    binding = eb.resolve_execution_binding({**claimed, "owner_approved": True, "assignee": "cursor"})
    return {
        "ok": True,
        "task_id": tid,
        "claim_token": token,
        "lease_until": claimed.get("lease_until"),
        "pinned_model": CURSOR_PINNED_MODEL,
        "model_policy": "CURSOR_OPS_PINNED_MODEL; no Auto/Max/Ultra",
        "worktree": worktree_path,
        "repo": repo,
        "work_branch": claimed.get("work_branch"),
        "title": claimed.get("title"),
        "objective": (claimed.get("objective") or claimed.get("title") or "")[:4000],
        "checklist": claimed.get("checklist") or [],
        "correlation_id": claimed.get("correlation_id"),
        "execution_binding": binding,
        "session": classified.get("interactive_session"),
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
    if not tid or not tok:
        return {"ok": False, "error": "task_id_and_claim_token_required"}
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid, "claim_token": tok})
    if not task:
        return {"ok": False, "error": "claim_token_mismatch_or_task_missing", "task_id": tid}

    normalized = (status or "completed").strip().lower()
    if normalized not in {"completed", "failed", "blocked"}:
        return {"ok": False, "error": "invalid_status", "allowed": ["completed", "failed", "blocked"]}

    now = _now()
    ev = dict(evidence or {})
    if commit_sha:
        ev["commit_sha"] = commit_sha.strip()
    ev.setdefault("completed_by", "cursor")
    ev.setdefault("effective_model", task.get("effective_model") or CURSOR_PINNED_MODEL)
    ev.setdefault("host", _host())

    db[OPS_TASKS_COL].update_one(
        {"task_id": tid, "claim_token": tok},
        {
            "$set": {
                "status": normalized,
                "updated_at": now,
                "completed_at": now if normalized == "completed" else None,
                "evidence": ev,
            },
            "$inc": {"revision": 1},
        },
    )
    event = "task.completed" if normalized == "completed" else "task.failed"
    _publish_task_event(event, {**task, "status": normalized}, actor="cursor", status=normalized, payload=ev)
    return {"ok": True, "task_id": tid, "status": normalized, "evidence": ev}
