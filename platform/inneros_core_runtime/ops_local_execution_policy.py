"""Admission for local / Dev Swarm / Temporal-bound work — prevents infinite machine saturation."""
from __future__ import annotations

from typing import Any

from inneros_core_runtime.execution_resource_guard import MAX_EXECUTIONS, MAX_MODEL_CALLS, MAX_TASK_SECONDS

LOCAL_PROVIDERS = frozenset({
    "dev_swarm",
    "dev-swarm",
    "ralfia",
    "local",
    "temporal",
    "local-amd-5",
    "local-intel-4",
    "local_amd_5",
    "local_intel_4",
    "qwen",
    "ollama",
})


def local_execution_denial(task: dict[str, Any], *, provider: str) -> str:
    target = provider.strip().lower().replace("_", "-")
    if target not in LOCAL_PROVIDERS and not target.startswith("local-"):
        return ""
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    if task.get("execution_stop") or task.get("superseded_by"):
        return "task_stopped_or_superseded"
    if bool(task.get("do_not_auto_dispatch")) or bool(payload.get("do_not_auto_dispatch")):
        return "manual_dispatch_only"
    guard = task.get("resource_guard") or {}
    if guard.get("stop_reason"):
        return "resource_guard_stopped"
    try:
        attempts = int(guard.get("attempts") or 0)
        model_calls = int(guard.get("model_calls") or 0)
        elapsed = float(guard.get("elapsed_seconds") or 0)
    except (ValueError, TypeError):
        return "invalid_resource_guard"
    if attempts >= MAX_EXECUTIONS:
        return "local_execution_budget_exhausted"
    if model_calls >= MAX_MODEL_CALLS:
        return "local_model_call_budget_exhausted"
    if elapsed >= MAX_TASK_SECONDS:
        return "local_execution_time_budget_exhausted"
    return ""
