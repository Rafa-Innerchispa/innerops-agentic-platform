"""Canonical awaiting_*_claim status for interactive IDE ops tasks."""

from __future__ import annotations

from typing import Any

from inneros_core_runtime.execution_binding import normalize_provider

_PROVIDER_AWAITING: dict[str, str] = {
    "cursor": "awaiting_cursor_claim",
    "codex": "awaiting_codex_claim",
    "antigravity": "awaiting_antigravity_claim",
    "gemini": "awaiting_gemini_claim",
}


def awaiting_claim_status_for_provider(provider: str) -> str:
    key = normalize_provider(provider)
    return _PROVIDER_AWAITING.get(key, "awaiting_ide_claim")


def awaiting_claim_status_for_task(task: dict[str, Any] | None) -> str:
    if not task:
        return awaiting_claim_status_for_provider("cursor")
    prov = str(
        task.get("assignee")
        or task.get("assigned_to")
        or task.get("preferred_provider")
        or task.get("owner")
        or "cursor"
    ).strip()
    return awaiting_claim_status_for_provider(prov)
