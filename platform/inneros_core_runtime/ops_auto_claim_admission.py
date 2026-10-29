"""Shared fail-closed admission policy for automatic InnerOS task claims.

An inbox ACK is never execution. Auto-claim requires a persisted owner
authorization, the assigned runner's readiness, and a claimable lifecycle
state. Never treat a self-declared payload flag as owner authorization.
"""
from __future__ import annotations

import os
from typing import Any

WAITING = frozenset({"queued", "waiting_for_binding", "waiting_for_model_binding", "awaiting_ide_claim"})
ACTIVE = frozenset({"claimed", "in_progress", "running", "verification"})
TERMINAL = frozenset({"completed", "done", "failed", "cancelled", "canceled", "superseded", "archived"})
PAUSED = frozenset({"awaiting_deploy_approval", "blocked_with_cause"})
INTERNAL_ALIASES = frozenset({
    "dev_swarm", "dev-swarm", "ralfia", "local", "temporal",
    "local-amd-5", "local-intel-4", "local_amd_5", "local_intel_4",
})


def _provider(task: dict[str, Any]) -> str:
    return str(task.get("assignee") or task.get("assigned_to") or task.get("preferred_provider") or "").strip().lower().replace("_", "-")


def claim_admission(
    task: dict[str, Any],
    *,
    provider: str,
    ready: bool,
    not_ready_reason: str = "provider_not_ready",
) -> dict[str, Any]:
    """Classify without claiming, changing status, or transferring a worktree."""
    owner = _provider(task)
    target = provider.strip().lower().replace("_", "-")
    status = str(task.get("status") or "").strip().lower()
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    result: dict[str, Any] = {
        "task_id": str(task.get("task_id") or ""),
        "provider": target,
        "status": status,
        "eligible": False,
    }

    def denied(reason: str) -> dict[str, Any]:
        return {**result, "reason": reason}

    if owner != target:
        return denied("different_assignee")
    if status in TERMINAL:
        return denied("terminal_task")
    if status in PAUSED:
        return denied("execution_paused_awaiting_owner")
    if status in ACTIVE:
        return denied("already_claimed" if task.get("claim_token") else "active_without_claim")
    if bool(task.get("do_not_auto_dispatch")) or bool(payload.get("do_not_auto_dispatch")):
        return denied("manual_dispatch_only")
    if target in INTERNAL_ALIASES:
        if status != "proposed":
            return denied("internal_task_not_proposed")
    elif status not in WAITING and status != f"awaiting_{target}_claim":
        return denied("not_claimable_state")
    if target not in INTERNAL_ALIASES and not task.get("owner_authorized_at"):
        # payload.owner_approved and autonomy prose are not authenticated grants.
        return denied("owner_authorization_not_recorded")
    if not ready:
        return denied(not_ready_reason)
    return {**result, "eligible": True, "reason": "ready_for_claim"}


def _autopilot_owner_trust_enabled() -> bool:
    return os.getenv("INNEROS_OPS_OWNER_AUTH_AUTOPILOT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def maybe_record_autopilot_owner_auth(task: dict[str, Any], *, provider: str) -> dict[str, Any]:
    """Record owner_authorized_at for private-cluster autopilot (not a WhatsApp ACK).

    Gated by INNEROS_OPS_OWNER_AUTH_AUTOPILOT. Never applies to do_not_auto_dispatch tasks.
    """
    if not _autopilot_owner_trust_enabled():
        return {"ok": False, "skipped": "autopilot_owner_trust_disabled"}
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    if bool(task.get("do_not_auto_dispatch")) or bool(payload.get("do_not_auto_dispatch")):
        return {"ok": False, "skipped": "manual_dispatch_only"}
    if task.get("owner_authorized_at"):
        return {"ok": True, "skipped": "already_authorized", "task_id": str(task.get("task_id") or "")}
    from inneros_core_runtime import interactive_ops_runner as ior

    tid = str(task.get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    return ior.authorize_ops_task(
        provider,
        tid,
        owner_actor=str(os.getenv("RALFIA_OWNER_ID") or "INNEROS_AUTOPILOT"),
        channel="autopilot_trust",
    )


def pending_admission_summary(
    tasks: list[dict[str, Any]],
    *,
    provider: str,
    ready: bool,
    not_ready_reason: str = "provider_not_ready",
    max_examples: int = 20,
) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    for task in tasks:
        decision = claim_admission(task, provider=provider, ready=ready, not_ready_reason=not_ready_reason)
        reason = str(decision["reason"])
        reasons[reason] = reasons.get(reason, 0) + 1
        if len(examples) < max_examples and reason not in {"terminal_task", "different_assignee"}:
            examples.append({k: decision[k] for k in ("task_id", "provider", "status", "eligible", "reason")})
    return {"provider": provider, "inspected": len(tasks), "reasons": reasons, "examples": examples}
