"""Pause Cursor/scheduler loops when deploy or host-mutation evidence is missing.

Code authorization and passing unit tests do not authorize production deploy.
Tasks must enter AWAITING_DEPLOY_APPROVAL (or BLOCKED_WITH_CAUSE) once, without
Temporal reopen, headless respawn, or dev_swarm requeue until owner deploy grant.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from inneros_core_runtime import ops_completion_policy as ocp

STATUS_AWAITING_DEPLOY = "awaiting_deploy_approval"
STATUS_BLOCKED_CAUSE = "blocked_with_cause"

_PAUSE_STATUSES = frozenset({STATUS_AWAITING_DEPLOY, STATUS_BLOCKED_CAUSE})

_GATE_MARKERS = (
    "host/deployment",
    "observed host mutation",
    "observed_host_mutation",
    "deployment_requires",
    "deploy_owner",
    "deploy_approval",
    "awaiting_deploy",
    "deployment_requires_owner",
    "mutate production",
)

_POLICY_MARKERS = _GATE_MARKERS + (
    "evidence_required",
    "text_only",
    "commit_sha",
    "objective_paths",
    "completion prohibited",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def gate_message_implies_deploy_pause(message: str) -> bool:
    msg = (message or "").lower()
    return any(m in msg for m in _GATE_MARKERS)


def completion_policy_blocked_message(message: str) -> bool:
    msg = (message or "").lower()
    return any(m in msg for m in _POLICY_MARKERS)


def task_implies_deploy_pause(task: dict[str, Any]) -> bool:
    if str(task.get("status") or "").lower() in _PAUSE_STATUSES:
        return True
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    if payload.get("requires_deploy_approval") is True or payload.get("awaiting_deploy_approval"):
        return True
    if task.get("execution_paused_for_deploy") is True:
        return True
    cause = str(task.get("blocked_with_cause") or payload.get("blocked_with_cause") or "").lower()
    if cause.startswith("awaiting_deploy") or cause.startswith("deploy_"):
        return True
    return ocp.objective_implies_deployment(task)


def execution_automation_frozen(task: dict[str, Any]) -> bool:
    """True when autopilot, headless spawn, or temporal reopen must not run."""
    if bool(task.get("do_not_auto_dispatch")):
        return True
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    if bool(payload.get("do_not_auto_dispatch")):
        return True
    if str(task.get("status") or "").lower() in _PAUSE_STATUSES:
        return True
    hl = task.get("headless_last_result") if isinstance(task.get("headless_last_result"), dict) else {}
    if hl.get("completion_policy_blocked") is True and task_implies_deploy_pause(task):
        return True
    if task.get("execution_paused_for_deploy") is True:
        return True
    return False


def completion_requires_deploy_pause(task: dict[str, Any], evidence: dict[str, Any] | None) -> bool:
    """A coding+deploy task cannot submit COMPLETED before observed host postconditions.

    Uses the same host receipt criterion as the terminal completion policy.
    Never converts an ordinary transient coding/provider error into deploy pause.
    """
    if not task_implies_deploy_pause(task):
        return False
    return not ocp._deployment_host_evidence_ok(dict(evidence or {}))


def classify_terminal_pause_status(task: dict[str, Any], gate_message: str) -> str:
    """Map a fail-closed gate message to a durable pause status."""
    if gate_message_implies_deploy_pause(gate_message) or task_implies_deploy_pause(task):
        return STATUS_AWAITING_DEPLOY
    if completion_policy_blocked_message(gate_message):
        return STATUS_BLOCKED_CAUSE
    return "blocked"


def blocked_with_cause_code(status: str, gate_message: str) -> str:
    if status == STATUS_AWAITING_DEPLOY:
        return "awaiting_deploy_approval:host_mutation_or_runtime_deploy"
    msg = (gate_message or "completion_gate_failed")[:240]
    return f"blocked_with_cause:{msg}"


def build_pause_mongo_patch(
    task: dict[str, Any],
    *,
    gate_message: str,
    evidence: dict[str, Any] | None = None,
    actor: str = "cursor",
) -> dict[str, Any]:
    """Mongo $set fields for a single-shot deploy/policy pause (CAS-friendly)."""
    status = classify_terminal_pause_status(task, gate_message)
    cause = blocked_with_cause_code(status, gate_message)
    payload = dict(task.get("payload") or {})
    payload["awaiting_deploy_approval"] = status == STATUS_AWAITING_DEPLOY
    payload["requires_deploy_approval"] = payload.get("requires_deploy_approval") or status == STATUS_AWAITING_DEPLOY
    payload["blocked_with_cause"] = cause
    ev = dict(evidence or {})
    ev.setdefault("blocked_with_cause", cause)
    ev.setdefault("pause_reason", cause)
    if status == STATUS_AWAITING_DEPLOY:
        ev.setdefault("awaiting_deploy_approval", True)
    now = _utc_now()
    return {
        "status": status,
        "do_not_auto_dispatch": True,
        "execution_paused_for_deploy": status == STATUS_AWAITING_DEPLOY,
        "blocked_with_cause": cause,
        "deploy_pause_at": now,
        "deploy_pause_actor": actor,
        "deploy_pause_gate_message": (gate_message or "")[:2000],
        "payload": payload,
        "candidate_evidence": ev,
        "updated_at": now,
        "updated_by": actor,
    }


def should_skip_dev_swarm_requeue(task: dict[str, Any], blob: str) -> bool:
    if execution_automation_frozen(task):
        return True
    lower = (blob or "").lower()
    return any(m in lower for m in _GATE_MARKERS)


def headless_resume_allowed(task: dict[str, Any]) -> bool:
    if execution_automation_frozen(task):
        return False
    status = str(task.get("status") or "").lower()
    if status in {"verification", "failed", STATUS_AWAITING_DEPLOY, STATUS_BLOCKED_CAUSE}:
        return False
    if status == "blocked" and not task.get("cursor_retry_requested"):
        return False
    return True


def cursor_claimable_statuses() -> frozenset[str]:
    return frozenset(
        {
            "queued",
            "waiting_for_binding",
            "awaiting_cursor_claim",
            "waiting_for_model_binding",
        }
    )


def simulate_autopilot_spawn_decisions(tasks: list[dict[str, Any]]) -> dict[str, int]:
    """Offline helper for scheduler regression (no Mongo). Returns spawn/claim/skip counts."""
    spawn = claim = skip = 0
    for task in tasks:
        if not headless_resume_allowed(task):
            skip += 1
            continue
        status = str(task.get("status") or "").lower()
        if status in cursor_claimable_statuses() and not execution_automation_frozen(task):
            claim += 1
        elif status in {"in_progress", "claimed"} and not task.get("headless_execution_started_at"):
            spawn += 1
        else:
            skip += 1
    return {"spawn": spawn, "claim": claim, "skip": skip, "total": len(tasks)}
