"""Fail-closed COMPLETED_VERIFIED gate for terminal ops transitions.

Agent session text, Mongo verification, Temporal completion RPC, and PR merge
must not mark a task completed unless every criterion in this module passes.
"""

from __future__ import annotations

import asyncio
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime import ops_completion_policy as ocp
from inneros_core_runtime import ops_task_requirements as otr

_GLOBAL_DENIAL = re.compile(
    r"(?:"
    r"no\s+completed\s+global|not\s+completed\s+global|"
    r"no\s+es\s+completed|jam[aá]s\s+completed|"
    r"never\s+(?:mark\s+)?completed|"
    r"\*\*no\s+completed\*\*|"
    r"estado\s+global\s+es\s+in_progress|"
    r"global\s+status\s*[:=]\s*(?:in_progress|blocked|failed)"
    r")",
    re.IGNORECASE,
)

_SYNTHETIC_CANARY = frozenset({"SYNTHETIC_CANARY_PASS", "BOUNDED_CANARY_PASS", "CANARY_TEXT_ONLY"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_blobs(task: dict[str, Any], evidence: dict[str, Any] | None) -> str:
    ev = dict(evidence or {})
    chunks: list[str] = []
    for root in (ev, task):
        for key in (
            "notes",
            "report",
            "summary",
            "agent_report",
            "checkpoint_body",
            "objective",
            "title",
        ):
            val = root.get(key)
            if isinstance(val, str) and val.strip():
                chunks.append(val)
    nested = ev.get("agent_result") if isinstance(ev.get("agent_result"), dict) else {}
    for key in ("response", "summary", "report"):
        val = nested.get(key)
        if isinstance(val, str) and val.strip():
            chunks.append(val)
    return "\n".join(chunks)


def agent_denies_global_completion(task: dict[str, Any], evidence: dict[str, Any] | None) -> str | None:
    ev = dict(evidence or {})
    if ev.get("global_completion") is False or ev.get("global_completion_ack") is False:
        return "agent_global_completion_denied_flag"
    blob = _text_blobs(task, ev)
    if _GLOBAL_DENIAL.search(blob):
        return "agent_report_denies_global_completion"
    return None


def shared_pre_temporal_denials(task: dict[str, Any], evidence: dict[str, Any] | None) -> list[str]:
    """Checks used by Mongo finalize and Temporal activity_validate_completion_gate (no recursion)."""
    tid = str(task.get("task_id") or "")
    ev = dict(evidence or {})
    reasons: list[str] = []

    deny = agent_denies_global_completion(task, ev)
    if deny:
        reasons.append(deny)

    amend = otr.completion_blocked_by_amendments(tid)
    if amend.get("blocked"):
        reasons.append(str(amend.get("error") or "pending_requirements_amendments"))

    if task.get("pending_temporal_completion"):
        reasons.append("pending_temporal_completion")

    synth = _synthetic_provider(ev)
    if synth:
        reasons.append(synth)

    deploy_err = _deploy_approval_missing(task, ev)
    if deploy_err:
        reasons.append(deploy_err)

    sha_err = _expected_main_sha_mismatch(task, ev)
    if sha_err:
        reasons.append(sha_err)

    return reasons


def _envelope_from_task(task: dict[str, Any]) -> dict[str, Any]:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    env = {**payload, **task}
    env.setdefault("task_class", task.get("task_class") or payload.get("task_class") or "coding")
    env.setdefault("evidence_required", task.get("evidence_required") or payload.get("evidence_required") or [])
    return env


def _agent_result_from_evidence(task: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    ev = dict(evidence)
    nested = ev.pop("agent_result", None)
    base = dict(nested) if isinstance(nested, dict) else {}
    merged = {**base, **ev}
    merged.setdefault("worktree", task.get("worktree") or task.get("local_worktree"))
    merged.setdefault("git_before_sha", task.get("git_baseline_sha"))
    return merged


def _run_temporal_gate(task: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    from inneros_core_runtime import temporal_activities as ta

    envelope = _envelope_from_task(task)
    agent_result = _agent_result_from_evidence(task, evidence)
    try:
        return asyncio.run(ta.activity_validate_completion_gate(envelope, agent_result))
    except RuntimeError:
        # Nested event loop (e.g. inside pytest-asyncio): use a fresh loop policy path.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(ta.activity_validate_completion_gate(envelope, agent_result))
        finally:
            loop.close()


def _deploy_approval_missing(task: dict[str, Any], evidence: dict[str, Any]) -> str | None:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    if payload.get("requires_deploy_approval") is not True and not payload.get("awaiting_deploy_approval"):
        if not ocp.objective_implies_deployment(task):
            return None
    if payload.get("deploy_approved_at") or evidence.get("deploy_approved_at"):
        return None
    if str(task.get("status") or "").lower() == "awaiting_deploy_approval":
        return "awaiting_deploy_approval"
    if payload.get("requires_deploy_approval") or payload.get("awaiting_deploy_approval"):
        return "deploy_owner_approval_required"
    if ocp.objective_implies_deployment(task):
        return "deployment_requires_owner_deploy_approval"
    return None


def _expected_main_sha_mismatch(task: dict[str, Any], evidence: dict[str, Any]) -> str | None:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    expected = str(
        payload.get("expected_main_sha")
        or task.get("expected_main_sha")
        or payload.get("merge_target_sha")
        or ""
    ).strip()
    if not expected or len(expected) != 40:
        return None
    got = str(evidence.get("commit_sha") or evidence.get("merge_sha") or evidence.get("sha") or "").strip()
    if got and got != expected:
        return "commit_sha_not_expected_main"
    return None


def _synthetic_provider(evidence: dict[str, Any]) -> str | None:
    for key in ("provider_result", "execution_mode", "canary_class", "result"):
        val = str(evidence.get(key) or "").strip().upper()
        if val in _SYNTHETIC_CANARY:
            return "synthetic_canary_not_real_provider"
    return None


def build_verified_receipt(
    task: dict[str, Any],
    evidence: dict[str, Any],
    *,
    model: str = "",
    gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ev = dict(evidence)
    return {
        "certification": "COMPLETED_VERIFIED",
        "task_id": task.get("task_id"),
        "requirements_version": task.get("requirements_version"),
        "generation": task.get("generation"),
        "claim_token": task.get("claim_token"),
        "worktree": task.get("worktree") or task.get("local_worktree"),
        "repo": task.get("repo") or task.get("related_project"),
        "branch": task.get("branch") or task.get("git_branch"),
        "before_sha": task.get("git_baseline_sha") or ev.get("git_before_sha"),
        "commit_sha": ev.get("commit_sha") or ev.get("sha"),
        "model": model or task.get("effective_model") or task.get("preferred_model"),
        "host": socket.gethostname().lower(),
        "verified_at": _utc_now(),
        "temporal_gate": gate or {},
        "test_results": ev.get("test_results"),
    }


def evaluate_global_completion(
    task: dict[str, Any],
    evidence: dict[str, Any] | None,
    *,
    model: str = "",
) -> dict[str, Any]:
    """Return ok=True only when COMPLETED_VERIFIED criteria are satisfied."""
    tid = str(task.get("task_id") or "")
    ev = dict(evidence or {})
    reasons = shared_pre_temporal_denials(task, ev)

    wt_path = str(task.get("worktree") or task.get("local_worktree") or ev.get("worktree") or "").strip()
    base = str(task.get("git_baseline_sha") or ev.get("git_before_sha") or "").strip()
    policy = ocp.validate_terminal_completion(
        task,
        ev,
    )
    if not policy.get("ok"):
        reasons.append(str(policy.get("error") or "completion_policy_failed"))

    temporal_gate = _run_temporal_gate(task, ev)
    if not temporal_gate.get("passed"):
        reasons.append(str(temporal_gate.get("error") or "temporal_completion_gate_failed"))

    if reasons:
        return {
            "ok": False,
            "certification": "INCOMPLETE",
            "task_id": tid,
            "reasons": reasons,
            "temporal_gate": temporal_gate,
            "policy": policy,
        }

    receipt = build_verified_receipt(task, ev, model=model, gate=temporal_gate)
    wt = Path(wt_path) if wt_path else None
    if wt and base and ocp.requires_git_commit(task):
        proof = ocp.validate_mutating_completion_evidence(task, ev, worktree=wt, before_sha=base)
        if proof:
            return {
                "ok": False,
                "certification": "INCOMPLETE",
                "task_id": tid,
                "reasons": [proof],
                "temporal_gate": temporal_gate,
            }

    return {
        "ok": True,
        "certification": "COMPLETED_VERIFIED",
        "task_id": tid,
        "receipt": receipt,
        "temporal_gate": temporal_gate,
        "policy": policy,
    }
