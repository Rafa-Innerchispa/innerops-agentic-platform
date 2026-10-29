"""Runner genérico claim/complete para agentes IDE (Cursor/Codex/Antigravity/Gemini/…)."""

from __future__ import annotations

import os
import secrets
import socket
from datetime import datetime, timezone, timedelta
from typing import Any

from raphiia_openai import mongo_store

from inneros_core_runtime import agent_provider_registry as apr
from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime.coordination_live import OPS_TASKS_COL, heartbeat_ops_task
from pathlib import Path

from inneros_core_runtime.cursor_ops_runner import (
    _evidence_to_agent_result,
    _lease_valid,
    _release_claim,
    _validate_completion_evidence,
)
from inneros_core_runtime import execution_receipts as receipts
from inneros_core_runtime import ops_completion_policy as ocp
from inneros_core_runtime import ops_execution_state as oes
from inneros_core_runtime import ops_lifecycle as ol

LEASE_SECONDS = int(os.getenv("INTERACTIVE_OPS_LEASE_SECONDS", os.getenv("CURSOR_OPS_LEASE_SECONDS", "3600")))
CLAIM_STATUSES = frozenset(
    {
        "queued",
        "waiting_for_binding",
        "awaiting_cursor_claim",
        "awaiting_codex_claim",
        "awaiting_antigravity_claim",
        "awaiting_gemini_claim",
        "awaiting_ide_claim",
        "waiting_for_model_binding",
        "blocked",
        "failed",
    }
)

_DEFAULT_PINNED: dict[str, tuple[str, str]] = {
    "cursor": ("CURSOR_OPS_PINNED_MODEL", "composer-2.5-fast"),
    "codex": ("CODEX_OPS_PINNED_MODEL", "gpt-5.6-terra"),
    "antigravity": ("ANTIGRAVITY_OPS_PINNED_MODEL", "gemini-3.7-flash-medium"),
    "gemini": ("GEMINI_OPS_PINNED_MODEL", "gemini-3.7-flash-medium"),
    "chatgpt": ("CHATGPT_OPS_PINNED_MODEL", "gpt-5.6-terra"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_until() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).isoformat()


def _host() -> str:
    return socket.gethostname()


def normalize_provider(provider: str) -> str:
    from inneros_core_runtime.execution_binding import normalize_provider as np

    return np(provider)


def pinned_model(provider: str) -> str:
    key = normalize_provider(provider)
    spec = apr.provider_spec(key)
    if spec and spec.get("pinned_model_env"):
        val = os.getenv(str(spec["pinned_model_env"]), "").strip()
        if val:
            return val
    env_key, default = _DEFAULT_PINNED.get(key, (f"{key.upper()}_OPS_PINNED_MODEL", ""))
    return os.getenv(env_key, default).strip()


def _validate_pinned_model(*, provider: str, task: dict[str, Any] | None = None) -> dict[str, Any] | None:
    expected = pinned_model(provider)
    if not expected:
        return {"ok": False, "error": f"{provider}_pinned_model_unset"}
    for field in ("preferred_model", "effective_model"):
        val = str((task or {}).get(field) or "").strip()
        if val and val != expected:
            return {"ok": False, "error": "model_not_pinned", "expected": expected, "got": val}
    return None


def _agent_result(provider: str, evidence: dict[str, Any], *, status: str) -> dict[str, Any]:
    channel = f"{normalize_provider(provider)}_interactive"
    base = _evidence_to_agent_result(evidence, status=status)
    base["completion_channel"] = channel
    base[f"{normalize_provider(provider)}_completion_status"] = status
    return base


def _awaiting_status(provider: str) -> str:
    key = normalize_provider(provider)
    if key == "cursor":
        return "awaiting_cursor_claim"
    if key == "codex":
        return "awaiting_codex_claim"
    return f"awaiting_{key}_claim"


def list_claimable_ops_tasks(*, provider: str, limit: int = 10, correlation_id: str | None = None) -> dict[str, Any]:
    prov = normalize_provider(provider)
    db = mongo_store.get_db()
    filt: dict[str, Any] = {
        "$or": [
            {"status": {"$in": sorted(CLAIM_STATUSES)}},
            {"status": "running", "assignee": prov, "claim_token": {"$exists": False}},
        ],
        "$and": [{"$or": [{"assignee": prov}, {"preferred_provider": prov}]}],
    }
    if correlation_id:
        filt["correlation_id"] = correlation_id.strip()
    rows = list(db[OPS_TASKS_COL].find(filt, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 50))))
    return {
        "ok": True,
        "provider": prov,
        "count": len(rows),
        "pinned_model": pinned_model(prov),
        "tasks": [
            {
                "task_id": t.get("task_id"),
                "title": t.get("title"),
                "status": t.get("status"),
                "correlation_id": t.get("correlation_id"),
                "owner_authorized": bool(t.get("owner_authorized_at")),
            }
            for t in rows
        ],
    }


def authorize_ops_task(
    provider: str,
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
    # Scoped, idempotent owner grant: never authorize another provider's task,
    # terminal task, or a task that already belongs to a running claim.
    owner = normalize_provider(provider)
    doc = db[OPS_TASKS_COL].find_one_and_update(
        {
            "task_id": tid,
            "assignee": owner,
            "status": {"$nin": ["completed", "done", "failed", "cancelled", "superseded", "archived"]},
            "claim_token": {"$exists": False},
        },
        {"$set": {
            "owner_authorized_at": now,
            "owner_authorized_by": owner_actor,
            "owner_authorization_channel": channel,
            "updated_at": now,
        }},
        return_document=True,
    )
    if not doc:
        existing = db[OPS_TASKS_COL].find_one(
            {"task_id": tid, "assignee": owner, "claim_token": {"$exists": False}},
            {"owner_authorized_at": 1, "_id": 0},
        )
        if isinstance(existing, dict) and existing.get("owner_authorized_at"):
            try:
                oes.refresh_current_execution_state(existing, event="owner_authorized", actor=owner_actor)
            except Exception:
                pass
            return {"ok": True, "task_id": tid, "provider": owner, "duplicate": True}
        return {"ok": False, "error": "task_not_found", "task_id": tid}
    out = {"ok": True, "task_id": tid, "provider": normalize_provider(provider)}
    try:
        oes.refresh_current_execution_state(doc, event="owner_authorized", actor=owner_actor)
    except Exception:
        pass
    return out




def _claim_worktree_with_retry(
    *,
    repo: str,
    base_branch: str,
    work_branch: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    idempotency_key: str,
    attempts: int = 4,
) -> dict[str, Any]:
    import time
    from inneros_core_runtime import local_execution_plane as lep

    lock = lep.acquire_lock(repo, actor, task_id, correlation_id, ttl_seconds=600)
    last: dict[str, Any] = {"ok": False, "error": "worktree_not_attempted"}
    try:
        for attempt in range(max(1, attempts)):
            last = lep.create_worktree(
                repo=repo,
                base_branch=base_branch,
                work_branch=work_branch,
                actor=actor,
                task_id=task_id,
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}-a{attempt}",
            )
            if last.get("ok") and str(last.get("worktree") or "").strip():
                return last
            time.sleep(min(2 ** attempt, 8))
    finally:
        if lock.get("ok"):
            lep.release_lock(repo, actor, task_id, correlation_id)
    return last


def claim_ops_task(
    provider: str,
    *,
    task_id: str | None = None,
    correlation_id: str | None = None,
    owner_approved: bool = False,
    owner_actor: str = "RAFAEL",
    require_cursor_session: bool = False,
) -> dict[str, Any]:
    prov = normalize_provider(provider)
    if prov == "cursor" and require_cursor_session:
        from inneros_core_runtime import cursor_execution_plane as cep

        classified = cep.classify_cursor_execution()
        if classified.get("execution_classification") not in {"partial", "headless_ready"}:
            return {"ok": False, "error": "cursor_session_not_ready", "classification": classified}

    db = mongo_store.get_db()
    filt: dict[str, Any] = {
        "$or": [
            {"status": {"$in": sorted(CLAIM_STATUSES)}},
            {"status": "running", "assignee": prov, "claim_token": {"$exists": False}},
        ],
        "$and": [{"$or": [{"assignee": prov}, {"preferred_provider": prov}]}],
    }
    if task_id:
        filt = {"task_id": task_id.strip(), **filt}
    elif correlation_id:
        filt["correlation_id"] = correlation_id.strip()
    task = db[OPS_TASKS_COL].find_one(filt, sort=[("created_at", -1)])
    if not task:
        return {"ok": False, "error": "no_claimable_task", "provider": prov}
    tid = str(task.get("task_id") or "")
    if not (bool(task.get("owner_authorized_at")) or owner_approved):
        return {"ok": False, "error": "owner_approval_required", "task_id": tid}
    from inneros_core_runtime import cursor_headless_lanes as _lanes

    allowed_host, route_reason = _lanes.should_this_node_run_task(task)
    if not allowed_host:
        return {
            "ok": False,
            "error": "execution_host_routing",
            "reason": route_reason,
            "task_id": tid,
            "provider": prov,
        }
    if prov == "cursor":
        from inneros_core_runtime import cursor_ops_runner as cor

        claim = cor.claim_ops_task(
            task_id=tid,
            owner_approved=owner_approved or bool(task.get("owner_authorized_at")),
            owner_actor=owner_actor,
        )
        return {**claim, "provider": "cursor"}
    pin = pinned_model(prov)
    token = secrets.token_hex(8)
    now = _now()
    spec = apr.provider_spec(prov) or {}
    lane = str(spec.get("default_lane") or "") or f"{prov}_interactive"
    claimed = db[OPS_TASKS_COL].find_one_and_update(
        {"task_id": tid, "$or": [{"status": {"$in": sorted(CLAIM_STATUSES)}}, {"status": "running", "assignee": prov, "claim_token": {"$exists": False}}]},
        {
            "$set": {
                "status": "claimed",
                "claimed_at": now,
                "claimed_by": prov,
                "claim_token": token,
                "claim_host": _host(),
                "lease_until": _lease_until(),
                "execution_lane": lane,
                "preferred_provider": prov,
                "assignee": prov,
                "preferred_model": pin,
                "effective_model": pin,
                "runner": f"{prov}_interactive",
                "updated_at": now,
            },
            "$inc": {"revision": 1},
        },
        return_document=True,
    )
    if not claimed:
        return {"ok": False, "error": "claim_conflict", "task_id": tid}
    model_err = _validate_pinned_model(provider=prov, task=claimed)
    if model_err:
        _release_claim(db, tid, reason=str(model_err.get("error")))
        return {**model_err, "task_id": tid}
    worktree_path = ""
    repo = str(claimed.get("repo") or "").strip()
    if repo:
        wt = _claim_worktree_with_retry(
            repo=repo,
            base_branch=str(claimed.get("base_ref") or "main"),
            work_branch=str(claimed.get("work_branch") or f"{prov}/ops-{tid.replace('ops_', '')}"),
            actor=prov,
            task_id=tid,
            correlation_id=str(claimed.get("correlation_id") or tid),
            idempotency_key=f"{prov}-claim-{tid}",
        )
        if wt.get("ok"):
            worktree_path = str(wt.get("worktree") or "")
        if not worktree_path:
            _release_claim(db, tid, reason="worktree_create_failed")
            return {"ok": False, "error": "worktree_required", "task_id": tid, "details": wt}
        baseline_sha = receipts.git_head(Path(worktree_path))
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid, "claim_token": token},
            {"$set": {"worktree": worktree_path, "git_baseline_sha": baseline_sha}, "$unset": {"claim_error": ""}},
        )
    from inneros_core_runtime import durable_coordination_spine

    handoff = durable_coordination_spine.signal_task_workflow(
        tid,
        "cursor_claim_handoff",
        {
            "claim_token": token,
            "status": "claimed",
            "preferred_provider": prov,
            "preferred_model": pin,
            "effective_model": pin,
            "worktree": worktree_path,
        },
    )
    try:
        oes.refresh_current_execution_state(
            {**claimed, "worktree": worktree_path, "status": "claimed"},
            event="claimed",
            actor=prov,
        )
    except Exception:
        pass
    heartbeat_ops_task(tid, actor=prov, phase="claimed", current_step=f"{prov}_interactive", last_progress=f"claim {_host()}")
    from inneros_core_runtime import ops_task_requirements as otr

    requirements_checkpoint = otr.process_checkpoint_amendments(tid, actor=prov)
    binding = eb.resolve_execution_binding({**claimed, "owner_approved": True})
    headless_spawn: dict[str, Any] | None = None
    try:
        from inneros_core_runtime import competition_lane_dispatch as cld

        task_now = db[OPS_TASKS_COL].find_one({"task_id": tid}) or claimed
        headless_spawn = cld.maybe_spawn_after_claim({**task_now, "worktree": worktree_path})
    except Exception:
        pass
    if (
        prov == "codex"
        and not headless_spawn
        and os.getenv("INNEROS_CODEX_SPAWN_ON_CLAIM", "1").strip().lower() in {"1", "true", "yes", "on"}
    ):
        try:
            from inneros_core_runtime import codex_headless_dispatch as cdx

            headless_spawn = cdx.spawn_headless_execute(tid)
        except Exception as exc:
            headless_spawn = {"ok": False, "error": "codex_headless_spawn_failed", "detail": str(exc)[:200]}
    if (
        prov == "antigravity"
        and not headless_spawn
        and os.getenv("INNEROS_ANTIGRAVITY_SPAWN_ON_CLAIM", "1").strip().lower() in {"1", "true", "yes", "on"}
    ):
        try:
            from inneros_core_runtime import antigravity_headless_dispatch as agd

            headless_spawn = agd.spawn_headless_execute(tid)
        except Exception as exc:
            headless_spawn = {"ok": False, "error": "antigravity_headless_spawn_failed", "detail": str(exc)[:200]}
    return {
        "ok": True,
        "provider": prov,
        "task_id": tid,
        "claim_token": token,
        "pinned_model": pin,
        "worktree": worktree_path,
        "temporal_handoff": handoff,
        "execution_binding": binding,
        "claim_host": _host(),
        "headless_spawn": headless_spawn,
        "requirements_checkpoint": requirements_checkpoint,
    }


def complete_ops_task(
    provider: str,
    task_id: str,
    *,
    claim_token: str,
    status: str = "completed",
    evidence: dict[str, Any] | None = None,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    prov = normalize_provider(provider)
    tid = (task_id or "").strip()
    tok = (claim_token or "").strip()
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid, "claim_token": tok, "assignee": prov})
    if not task:
        return {"ok": False, "error": "claim_token_mismatch_or_task_missing", "task_id": tid}
    if not _lease_valid(task):
        return {"ok": False, "error": "lease_expired", "task_id": tid}
    normalized = (status or "completed").strip().lower()
    from inneros_core_runtime import ops_task_requirements as otr

    amend_block = otr.completion_blocked_by_amendments(tid)
    if normalized == "completed" and amend_block.get("blocked"):
        return {"ok": False, "error": amend_block["error"], "task_id": tid, "pending_amendments": amend_block["pending"]}
    model_err = _validate_pinned_model(provider=prov, task=task)
    if model_err:
        return {**model_err, "task_id": tid}
    ev = dict(evidence or {})
    if normalized == "completed":
        expected_model = pinned_model(prov)
        for field in ("gemini_model", "effective_model", "runtime_model"):
            runtime_model = str(ev.get(field) or "").strip()
            if runtime_model and expected_model and runtime_model != expected_model:
                return {
                    "ok": False,
                    "error": "model_not_pinned",
                    "expected": expected_model,
                    "got": runtime_model,
                    "field": field,
                    "task_id": tid,
                }
    if commit_sha:
        ev["commit_sha"] = commit_sha.strip()
    wt_path = str(task.get("worktree") or task.get("local_worktree") or ev.get("worktree") or "").strip()
    base = str(task.get("git_baseline_sha") or ev.get("git_before_sha") or "").strip()
    if normalized == "completed" and ocp.requires_git_commit(task):
        if ocp.is_text_only_headless_evidence(ev):
            return {"ok": False, "error": "text_only_headless_executor_cannot_complete", "task_id": tid}
        if wt_path and base:
            runner_tests = ev.get("test_results") if isinstance(ev.get("test_results"), dict) else None
            built = receipts.completion_evidence_from_worktree(Path(wt_path), base)
            if built.get("ok"):
                ev = {**ev, **built["evidence"]}
                if runner_tests is not None:
                    ev["test_results"] = runner_tests
            elif not str(ev.get("commit_sha") or "").strip():
                return {
                    "ok": False,
                    "error": built.get("error") or "committed_objective_receipt_required",
                    "task_id": tid,
                    "receipt": built,
                }
    if normalized == "completed":
        ev_err = ocp.validate_mutating_completion_evidence(
            task,
            ev,
            worktree=Path(wt_path) if wt_path else None,
            before_sha=base,
        ) if ocp.requires_git_commit(task) else ocp.validate_completed_evidence(task, ev)
    else:
        ev_err = _validate_completion_evidence(normalized, ev)
    if ev_err:
        return {"ok": False, "error": ev_err, "task_id": tid}
    agent_result = _agent_result(prov, ev, status=normalized)
    from inneros_core_runtime import durable_coordination_spine

    completion_signal = {
        "cursor": "cursor_execution_complete",
        "codex": "cursor_execution_complete",
        "antigravity": "cursor_execution_complete",
        "gemini": "cursor_execution_complete",
    }.get(prov, "cursor_execution_complete")
    submitted = ol.submit_completion_with_temporal_fallback(
        tid,
        claim_token=tok,
        status=normalized,
        evidence=ev,
        agent_result=agent_result,
        actor=prov,
        signal_name=completion_signal,
    )
    try:
        oes.refresh_current_execution_state(
            {**task, "status": "verification"},
            event=f"{prov}_execution_complete",
            actor=prov,
        )
    except Exception:
        pass
    return {
        "ok": True,
        "task_id": tid,
        "status": "verification",
        "provider": prov,
        "temporal": submitted.get("temporal"),
        "temporal_deferred": submitted.get("temporal_deferred"),
        "chatgpt_handoff": submitted.get("chatgpt_handoff"),
        "evidence": ev,
    }
