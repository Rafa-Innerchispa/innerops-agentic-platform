"""Owner execution policy for development delegation.

The policy is intentionally small and serializable so MCP task contracts,
Resource Fabric routes and local workers all carry the same decision fields.
"""

from __future__ import annotations

from typing import Any


POLICY_ID = "owner-local-first-20260901"
POLICY_VERSION = "local_first_execution_policy_v1"
DEFAULT_PREFERRED_PROVIDER = "local-amd-5"
DEFAULT_PREFERRED_MODEL = "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ"
LOCAL_FIRST_TASK_CLASSES = frozenset(
    {
        "basic_ops",
        "build",
        "code_review",
        "coding",
        "development",
        "heavy_reasoning",
        "refactor",
        "tests_build",
    }
)
EXTERNAL_ALLOWED_REASONS = frozenset(
    {
        "capability_failure",
        "local_unavailable",
        "provider_specific_ide",
        "orchestration_only",
        "owner_override",
    }
)


def normalize_task_class(task_class: str | None) -> str:
    value = (task_class or "coding").strip().lower().replace("-", "_")
    return value or "coding"


def task_contract(
    *,
    task_class: str | None = "coding",
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
    fallback_reason: str | None = None,
    approval_id: str | None = None,
    owner_override: bool = False,
) -> dict[str, Any]:
    normalized = normalize_task_class(task_class)
    reason = (fallback_reason or "").strip()
    approval = (approval_id or "").strip()
    return {
        "owner_policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "execution_policy": "local_first",
        "local_first_required": normalized in LOCAL_FIRST_TASK_CLASSES,
        "task_class": normalized,
        "preferred_provider": preferred_provider or DEFAULT_PREFERRED_PROVIDER,
        "preferred_model": preferred_model or DEFAULT_PREFERRED_MODEL,
        "fallback_reason": reason or None,
        "approval_id": approval or None,
        "owner_override": bool(owner_override),
    }


def external_execution_decision(
    *,
    task_class: str | None = "coding",
    local_available: bool = True,
    fallback_reason: str | None = None,
    approval_id: str | None = None,
    owner_override: bool = False,
) -> dict[str, Any]:
    contract = task_contract(
        task_class=task_class,
        fallback_reason=fallback_reason,
        approval_id=approval_id,
        owner_override=owner_override,
    )
    reason = (fallback_reason or "").strip()
    approval = (approval_id or "").strip()
    if owner_override and approval:
        return {**contract, "ok": True, "decision": "allowed_by_owner_override"}
    if local_available and contract["local_first_required"]:
        return {**contract, "ok": False, "decision": "blocked_local_capable"}
    if not reason or not approval:
        return {**contract, "ok": False, "decision": "external_requires_reason_and_approval"}
    if reason not in EXTERNAL_ALLOWED_REASONS:
        return {**contract, "ok": False, "decision": "fallback_reason_not_allowed"}
    return {**contract, "ok": True, "decision": "allowed_after_local_blocker"}


def route_metadata(task_class: str | None = "coding") -> dict[str, Any]:
    contract = task_contract(task_class=task_class)
    return {
        "execution_policy": contract["execution_policy"],
        "owner_policy_id": contract["owner_policy_id"],
        "policy_version": contract["policy_version"],
        "preferred_provider": contract["preferred_provider"],
        "preferred_model": contract["preferred_model"],
        "fallback_reason": contract["fallback_reason"],
        "approval_id": contract["approval_id"],
        "local_first_required": contract["local_first_required"],
    }
