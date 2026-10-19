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


def _lease_valid(task: dict[str, Any]) -> bool:
    lease = str(task.get("lease_until") or "").strip()
    if not lease:
        return True
    return lease >= _now()


def _validate_pinned_model(*, task: dict[str, Any] | None = None) -> dict[str, Any] | None:
    expected = CURSOR_PINNED_MODEL.strip()
    if not expected:
        return {"ok": False, "error": "CURSOR_OPS_PINNED_MODEL_unset"}
    for field in ("preferred_model", "effective_model"):
        val = str((task or {}).get(field) or "").strip()
        if val and val != expected:
            return {"ok": False, "error": "model_not_pinned", "expected": expected, "got": val}
    return None


def _validate_completion_evidence(status: str, evidence: dict[str, Any] | None) -> str | None:
    normalized = (status or "").strip().lower()
    if normalized != "completed":
        return None
    ev = dict(evidence or {})
    sha = str(ev.get("commit_sha") or ev.get("sha") or "").strip()
    if sha:
        return None
    files = int(ev.get("objective_files_count") or 0)
    paths = list(ev.get("objective_paths") or [])
    if files > 0 and paths:
        return None
    tests = ev.get("test_results") or {}
    exit_code = tests.get("exit_code")
    if exit_code is not None and int(exit_code) == 0 and tests.get("ok", True):
        return None
    return (
        "evidence_required_for_completed: commit_sha, objective_paths+count, "
        "or test_results.exit_code=0"
    )


def _evidence_to_agent_result(evidence: dict[str, Any], *, status: str) -> dict[str, Any]:
    ev = dict(evidence or {})
    tests = ev.get("test_results") or {}
    out: dict[str, Any] = {
        "files_count": int(ev.get("objective_files_count") or 0),
        "objective_files_count": int(ev.get("objective_files_count") or 0),
        "objective_paths": list(ev.get("objective_paths") or []),
        "code_diff": str(ev.get("code_diff") or ""),
        "test_results": tests,
        "commit_sha": ev.get("commit_sha") or ev.get("sha"),
        "cursor_completion_status": status,
        "completion_channel": "cursor_interactive",
        "response": ev.get("notes") or ev.get("summary") or "",
    }
    for key, val in ev.items():
        if key not in out:
            out[key] = val
    return out


def _release_claim(db, tid: str, *, reason: str) -> None:
    from inneros_core_runtime.ops_awaiting_claim import awaiting_claim_status_for_task

    now = _now()
    task = db[OPS_TASKS_COL].find_one(
        {"task_id": tid},
        {"assignee": 1, "assigned_to": 1, "preferred_provider": 1, "owner": 1},
    ) or {}
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$set": {
                "status": awaiting_claim_status_for_task(task),
                "updated_at": now,
                "claim_error": reason[:500],
            },
            "$unset": {
                "claim_token": "",
                "claimed_at": "",
                "lease_until": "",
                "claimed_by": "",
                "claim_host": "",
            },
            "$inc": {"revision": 1},
        },
    )


def renew_ops_lease(task_id: str, claim_token: str, *, lease_seconds: int | None = None) -> dict[str, Any]:
    tid = (task_id or "").strip()
    tok = (claim_token or "").strip()
    if not tid or not tok:
        return {"ok": False, "error": "task_id_and_claim_token_required"}
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid, "claim_token": tok}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "claim_token_mismatch_or_task_missing", "task_id": tid}
    assignee = str(task.get("claimed_by") or task.get("assignee") or "").lower()
    if assignee and assignee not in {"cursor", ""}:
        return {"ok": False, "error": "renew_cursor_lease_wrong_assignee", "task_id": tid}
    sec = int(lease_seconds or LEASE_SECONDS)
    until = (datetime.now(timezone.utc) + timedelta(seconds=sec)).isoformat()
    now = _now()
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid, "claim_token": tok},
        {"$set": {"lease_until": until, "updated_at": now, "status": "in_progress"}, "$inc": {"revision": 1}},
    )
    heartbeat_ops_task(tid, actor="cursor", phase="lease_renewed", last_progress=f"lease extended {sec}s")
    return {"ok": True, "task_id": tid, "lease_until": until}


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
    existing = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if existing and existing.get("owner_authorized_at"):
        return {
            "ok": True,
            "task_id": tid,
            "owner_authorized_at": existing.get("owner_authorized_at"),
            "message": "Autorización vigente; reintento de claim sin nueva aprobación.",
            "authorization_reused": True,
        }
    if existing:
        from inneros_core_runtime import ops_task_materializer as otm

        gate = otm.authorization_blockers(existing, provider="cursor")
        if not gate.get("ok"):
            return {
                "ok": False,
                "error": gate.get("error"),
                "task_id": tid,
                "preflight": gate.get("preflight"),
                "message": gate.get("message"),
            }
        otm.persist_materialization(db, tid, gate["preflight"]["materialization"])
    now = _now()
    # Scoped, idempotent owner grant: never authorize another provider's task,
    # terminal task, or a task that already belongs to a running claim.
    owner = "cursor"
    doc = db[OPS_TASKS_COL].find_one_and_update(
        {"task_id": tid,
         "assignee": owner,
         "status": {"$nin": ["completed", "done", "failed", "cancelled", "superseded", "archived"]},
         "claim_token": {"$exists": False}},
        {"$set": {
            "owner_authorized_at": now,
            "owner_authorized_by": owner_actor,
            "owner_authorization_channel": channel,
            "updated_at": now,
        }},
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
    # A task claim must never mint a fake IDE heartbeat. Only an actual
    # authenticated Cursor session or a usable headless SDK key may execute.
    classified = cep.classify_cursor_execution()
    headless_exec = os.getenv("INNEROS_CURSOR_HEADLESS_EXECUTE", "1").strip().lower() in {"1", "true", "yes"}
    if classified.get("execution_classification") not in {"partial", "headless_ready"}:
        try:
            from inneros_core_runtime import cursor_api_credentials as cac

            if headless_exec and cac.cursor_api_key_status().get("present"):
                classified = {**classified, "execution_classification": "headless_ready", "headless_sdk_bypass": True}
            else:
                return {
                    "ok": False,
                    "error": "cursor_session_not_ready",
                    "classification": classified,
                    "hint": (
                        "Requiere consumidor Cursor auténtico (cursor_inbox_consumer / sesión IDE) "
                        "o headless SDK habilitado."
                    ),
                }
        except Exception:
            return {
                "ok": False,
                "error": "cursor_session_not_ready",
                "classification": classified,
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
    from inneros_core_runtime import cursor_headless_lanes as _lanes

    allowed, route_reason = _lanes.should_this_node_run_task(task)
    if not allowed:
        return {
            "ok": False,
            "error": "execution_host_routing",
            "reason": route_reason,
            "task_id": tid,
        }
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

    model_err = _validate_pinned_model(task=claimed)
    if model_err:
        _release_claim(db, tid, reason=str(model_err.get("error")))
        return {**model_err, "task_id": tid}

    worktree_path = ""
    worktree_error: dict[str, Any] | None = None
    from inneros_core_runtime import ops_task_materializer as otm

    mat = otm.materialize_ops_task_execution(claimed, provider="cursor")
    repo = str(mat.get("repo") or "").strip()
    if mat.get("ok"):
        otm.persist_materialization(db, tid, mat)
        claimed = {**claimed, **mat}
    if repo:
        from inneros_core_runtime import local_execution_plane as lep

        branch = str(mat.get("work_branch") or claimed.get("work_branch") or f"cursor/ops-{tid.replace('ops_', '')}")
        from inneros_core_runtime.interactive_ops_runner import _claim_worktree_with_retry

        wt = _claim_worktree_with_retry(
            repo=repo,
            base_branch=str(mat.get("base_ref") or claimed.get("base_ref") or "main"),
            work_branch=branch,
            actor="cursor",
            task_id=tid,
            correlation_id=str(claimed.get("correlation_id") or tid),
            idempotency_key=f"cursor-claim-{tid}",
        )
        if wt.get("ok"):
            worktree_path = str(wt.get("worktree") or "")
        else:
            worktree_error = wt
        if not worktree_path:
            _release_claim(db, tid, reason="worktree_create_failed")
            return {
                "ok": False,
                "error": "worktree_required",
                "task_id": tid,
                "repo": repo,
                "details": worktree_error or {"error": "empty_worktree_path"},
            }
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid, "claim_token": token},
            {"$set": {"worktree": worktree_path, "updated_at": _now()}},
        )

    from inneros_core_runtime import durable_coordination_spine

    handoff_payload = {
        "claim_token": token,
        "status": "claimed",
        "claim_host": _host(),
        "worktree": worktree_path,
        "preferred_model": CURSOR_PINNED_MODEL,
        "effective_model": CURSOR_PINNED_MODEL,
        "owner_approved": True,
        "owner_authorized_at": claimed.get("owner_authorized_at"),
    }
    temporal_handoff = durable_coordination_spine.signal_task_workflow(
        tid,
        "cursor_claim_handoff",
        handoff_payload,
        workflow_id=str(claimed.get("workflow_id") or ""),
    )

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
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid, "claim_token": token},
        {"$set": {"status": "in_progress", "execution_started_at": now, "updated_at": now}, "$inc": {"revision": 1}},
    )
    heartbeat_ops_task(
        tid,
        actor="cursor",
        phase="in_progress",
        current_step="cursor_interactive",
        last_progress=f"Claimed on {_host()} model={CURSOR_PINNED_MODEL}",
    )

    binding = eb.resolve_execution_binding({**claimed, "owner_approved": True, "assignee": "cursor", "status": "in_progress"})
    result: dict[str, Any] = {
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
        "temporal_handoff": temporal_handoff,
        "session": classified.get("interactive_session"),
    }
    if os.getenv("INNEROS_CURSOR_SPAWN_ON_CLAIM", "1").strip().lower() in {"1", "true", "yes"}:
        from inneros_core_runtime.cursor_headless_dispatch import spawn_headless_execute

        result["headless_spawn"] = spawn_headless_execute(tid)
    return result


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

    if not _lease_valid(task):
        return {"ok": False, "error": "lease_expired", "task_id": tid, "lease_until": task.get("lease_until")}

    model_err = _validate_pinned_model(task=task)
    if model_err:
        return {**model_err, "task_id": tid}

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

    ev_err = _validate_completion_evidence(normalized, ev)
    if ev_err:
        return {"ok": False, "error": ev_err, "task_id": tid}

    agent_result = _evidence_to_agent_result(ev, status=normalized)
    if normalized in {"failed", "blocked"}:
        agent_result["blocked"] = True

    from inneros_core_runtime import durable_coordination_spine

    signal_payload = {
        "submitted": True,
        "status": normalized,
        "agent_result": agent_result,
        "evidence": ev,
        "claim_token": tok,
        "actor": "cursor",
        "at": now,
    }
    wf_id = str(task.get("workflow_id") or "")
    temporal = durable_coordination_spine.signal_task_workflow(
        tid,
        "cursor_execution_complete",
        signal_payload,
        workflow_id=wf_id,
    )
    _temporal_err = str(temporal.get("error") or "").lower()
    if not temporal.get("ok") and (
        "already completed" in _temporal_err or "workflow not found" in _temporal_err
    ):
        from inneros_core_runtime.ops_temporal_recovery import reopen_ops_temporal_execution

        reopened = reopen_ops_temporal_execution(
            tid,
            reason="auto_reopen_terminal_workflow_for_completion",
            actor="cursor_ops_runner",
        )
        if reopened.get("ok") and not reopened.get("skipped"):
            task = db[OPS_TASKS_COL].find_one({"task_id": tid, "claim_token": tok}) or task
            wf_id = str(task.get("workflow_id") or wf_id)
            temporal = durable_coordination_spine.signal_task_workflow(
                tid,
                "cursor_execution_complete",
                signal_payload,
                workflow_id=wf_id,
            )
    if not temporal.get("ok"):
        return {
            "ok": False,
            "error": "temporal_completion_signal_failed",
            "task_id": tid,
            "details": temporal,
            "hint": "El workflow Temporal debe estar vivo (handoff Cursor). No se escribió completed en Mongo.",
        }

    db[OPS_TASKS_COL].update_one(
        {"task_id": tid, "claim_token": tok},
        {
            "$set": {
                "status": "verification",
                "executed_at": now,
                "updated_at": now,
                "completion_submitted_at": now,
                "candidate_evidence": ev,
                "candidate_agent_result": agent_result,
            },
            "$inc": {"revision": 1},
        },
    )
    heartbeat_ops_task(
        tid,
        actor="cursor",
        phase="executed",
        current_step="cursor_execution_complete",
        last_progress="Evidence submitted; awaiting Temporal verification gate",
    )
    _publish_task_event(
        "task.verification",
        {**task, "status": "verification"},
        actor="cursor",
        status="verification",
        payload={"evidence": ev, "temporal": temporal},
    )
    return {
        "ok": True,
        "task_id": tid,
        "status": "verification",
        "evidence": ev,
        "temporal": temporal,
        "message": "Evidencia enviada a Temporal; estado final tras gate de verificación.",
    }
