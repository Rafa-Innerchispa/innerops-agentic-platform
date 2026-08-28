"""AG-25 durable project-control loop.

This is the one persistent control cycle used by the coordination daemon:
A2A catalog work -> Dev Swarm -> executor -> Integration Guardian -> liveness.
It intentionally does not depend on an active ChatGPT conversation.
"""
from __future__ import annotations

from typing import Any

from raphiia_openai import a2a_controller, dev_swarm_scheduler, integration_guardian, local_execution_plane, work_liveness

CONTROLLER_VERSION = "1.1.0"
_RUNTIME_PATCHED = False


def _ensure_scheduler_runtime_contract() -> dict[str, Any]:
    """Keep live legacy imports aligned with canonical Registry semantics.

    Canonical source contains the same fixes. This compatibility layer makes the
    persistent daemon safe during staged deployment and can later be removed.
    """
    global _RUNTIME_PATCHED
    if _RUNTIME_PATCHED:
        return {"ok": True, "patched": False, "idempotent": True}

    for prefix in ("inneros_core_runtime/", "platform/inneros_core_runtime/"):
        if prefix not in dev_swarm_scheduler.PRODUCT_PREFIXES:
            dev_swarm_scheduler.PRODUCT_PREFIXES = tuple(dev_swarm_scheduler.PRODUCT_PREFIXES) + (prefix,)

    original = dev_swarm_scheduler._fanout_base_snapshot

    def registry_authoritative_snapshot(repo: str, base_ref: str = "") -> dict[str, Any]:
        result = original(repo, base_ref=base_ref)
        if not result.get("ok"):
            return result
        policy = local_execution_plane.repo_policy_status(repo)
        if policy.get("ok") and policy.get("registry_backed"):
            registered = (policy.get("policy") or {}).get("profile")
            if registered:
                result["profile"] = registered
                result["profile_source"] = "project_runtime_registry"
        return result

    dev_swarm_scheduler._fanout_base_snapshot = registry_authoritative_snapshot
    _RUNTIME_PATCHED = True
    return {"ok": True, "patched": True, "executor_version": getattr(dev_swarm_scheduler, "EXECUTOR_VERSION", "unknown")}


def run_cycle(limit: int = 8, executor_limit: int = 4, dry_run: bool = False) -> dict[str, Any]:
    """Run one complete autonomous AG-25 project cycle."""
    runtime_contract = _ensure_scheduler_runtime_contract()
    a2a = a2a_controller.controller_tick(limit=max(1, min(limit, 8)), dry_run=dry_run)
    swarm = dev_swarm_scheduler.scheduler_tick(limit=limit, dry_run=dry_run)
    executor = dev_swarm_scheduler.executor_tick(limit=executor_limit, dry_run=dry_run)
    # Verify in the same cycle that produced the commit. Delaying Guardian to
    # the next controller iteration can leave it inspecting a cleaned worktree.
    guardian = integration_guardian.guardian_tick(limit=max(1, min(limit, 8)), dry_run=dry_run)
    liveness = work_liveness.evaluate_tick(
        available=int(swarm.get("available") or 0),
        selected=list(swarm.get("selected") or []),
        skipped=list(swarm.get("skipped") or []),
        filtered=list(swarm.get("filtered") or []),
        dry_run=dry_run,
    )
    return {
        "ok": bool(swarm.get("ok", True)) and bool(a2a.get("ok", True)) and bool(guardian.get("ok", True)),
        "controller": "AG-25",
        "controller_version": CONTROLLER_VERSION,
        "runtime_contract": runtime_contract,
        "executor_version": getattr(dev_swarm_scheduler, "EXECUTOR_VERSION", "unknown"),
        "a2a": a2a,
        "guardian": guardian,
        "swarm": swarm,
        "executor": executor,
        "liveness": liveness,
        "selected_count": len(swarm.get("selected") or []),
        "skip_count": len(swarm.get("skipped") or []),
        "active_worker_count": int(swarm.get("active_worker_count") or 0),
        "transport": "a2a+mcp-racb",
    }
