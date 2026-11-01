"""Fail-closed paid headless admission for Cursor, Codex, Antigravity, Gemini, and future IDE agents."""
from __future__ import annotations

from typing import Any

PAID_HEADLESS_PROVIDERS = frozenset({"cursor", "codex", "antigravity", "gemini"})
EXECUTABLE_STATUSES = frozenset({"claimed", "in_progress", "running"})
MAX_AUTOMATIC_DISPATCHES = 3


def _payload(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("payload")
    return raw if isinstance(raw, dict) else {}


def task_provider(task: dict[str, Any]) -> str:
    return str(task.get("assignee") or task.get("assigned_to") or "").strip().lower()


def headless_denial(
    task: dict[str, Any],
    *,
    provider: str | None = None,
    check_budget: bool = True,
) -> str:
    """Empty string means allowed; otherwise machine-readable denial reason."""
    from inneros_core_runtime import ops_deploy_execution_pause as odep

    if odep.execution_automation_frozen(task):
        return "execution_automation_frozen"
    payload = _payload(task)
    expected = (provider or task_provider(task)).strip().lower()
    if not expected:
        return "provider_required"
    if expected not in PAID_HEADLESS_PROVIDERS:
        return "unsupported_paid_provider"
    status = str(task.get("status") or "").lower()
    if status not in EXECUTABLE_STATUSES:
        return "task_not_executable"
    if task.get("superseded_by"):
        return "task_superseded"
    if task.get("do_not_auto_dispatch") or payload.get("do_not_auto_dispatch"):
        return "manual_dispatch_only"
    if task.get("execution_paused_for_deploy") or payload.get("execution_paused_for_deploy"):
        return "execution_paused_for_deploy"
    if task.get("execution_stop"):
        return "owner_stopped_execution"
    if any(
        "interactive" in str(source.get("execution_lane") or "").lower()
        for source in (task, payload)
    ):
        return "interactive_lane"
    if task_provider(task) != expected:
        return "different_assignee"
    if expected in PAID_HEADLESS_PROVIDERS:
        if not task.get("claim_token") or not task.get("owner_authorized_at"):
            return "authorization_or_claim_missing"
    last = task.get("headless_last_result") or {}
    if last.get("completion_submitted") or last.get("completion_policy_blocked"):
        return "awaiting_completion_verification"
    if check_budget:
        try:
            attempts = int(task.get("headless_dispatch_attempts") or 0)
        except (ValueError, TypeError):
            return "invalid_dispatch_budget"
        if attempts < 0 or attempts >= MAX_AUTOMATIC_DISPATCHES:
            return "headless_dispatch_budget_exhausted"
    guard = task.get("resource_guard") or {}
    if guard.get("last_outcome") == "success":
        return "resource_success_already_submitted"
    if guard.get("stop_reason"):
        return "resource_guard_stopped"
    try:
        attempts = int(guard.get("attempts") or 0)
    except (ValueError, TypeError):
        return "invalid_resource_guard"
    from inneros_core_runtime.execution_resource_guard import MAX_EXECUTIONS

    if attempts >= MAX_EXECUTIONS:
        return "resource_execution_budget_exhausted"
    return ""
