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


_INTERNAL_ASSIGNEES: frozenset[str] = frozenset(
    {"inneros_orchestrator", "orchestrator", "system", "dev_swarm", "local"}
)


def awaiting_claim_status_for_provider(provider: str) -> str:
    key = normalize_provider(provider)
    return _PROVIDER_AWAITING.get(key, "awaiting_ide_claim")


def awaiting_claim_status_for_task(task: dict[str, Any] | None) -> str:
    if not task:
        return awaiting_claim_status_for_provider("cursor")
    prov = str(task.get("preferred_provider") or task.get("claimed_by") or "").strip()
    if not prov:
        lane = str(task.get("execution_lane") or "").strip().lower()
        for p in _PROVIDER_AWAITING:
            if p in lane:
                prov = p
                break
    if not prov:
        assignee = str(task.get("assignee") or task.get("assigned_to") or "").strip()
        if assignee and assignee.lower() not in _INTERNAL_ASSIGNEES:
            prov = assignee
    if not prov:
        prov = str(task.get("owner") or "cursor").strip()
    return awaiting_claim_status_for_provider(prov)
