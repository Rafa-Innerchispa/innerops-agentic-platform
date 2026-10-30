"""Fail-closed admission shared by Cursor selection, dispatch and paid execution."""
from __future__ import annotations

from typing import Any


MAX_AUTOMATIC_DISPATCHES = 3


def headless_denial(task: dict[str, Any], *, check_budget: bool = True) -> str:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    if task.get("status") not in {"claimed", "in_progress", "running"}:
        return "task_not_executable"
    if task.get("superseded_by"):
        return "task_superseded"
    if task.get("do_not_auto_dispatch") or payload.get("do_not_auto_dispatch"):
        return "manual_dispatch_only"
    if task.get("execution_paused_for_deploy") or payload.get("execution_paused_for_deploy"):
        return "execution_paused_for_deploy"
    if task.get("execution_stop"):
        return "owner_stopped_execution"
    if any("interactive" in str(source.get("execution_lane") or "").lower()
           for source in (task, payload)):
        return "interactive_lane"
    if str(task.get("assignee") or task.get("assigned_to") or "").lower() != "cursor":
        return "different_assignee"
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
    return ""
