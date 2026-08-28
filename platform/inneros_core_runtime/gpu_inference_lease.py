"""Shared GPU inference lease for Dev Swarm, A2A and Voice."""

from __future__ import annotations

import os
from typing import Any

from raphiia_openai import dev_swarm_scheduler, racb_locks

GPU_INFERENCE_RESOURCE_PREFIX = "gpu:inference"
DEFAULT_GENERATION_SLOTS = 1
DEFAULT_LEASE_TTL_SECONDS = 900
VOICE_PRIORITY_AGENT = "voice_gateway"
CODING_AGENT = "dev_swarm"


def _node_id() -> str:
    snapshot = dev_swarm_scheduler.capacity_status()
    return str(snapshot.get("node") or (os.uname().nodename if hasattr(os, "uname") else "local"))


def _generation_resource_id(node: str, slot: int = 0) -> str:
    return f"{GPU_INFERENCE_RESOURCE_PREFIX}:{node}:generation:{slot}"


def _capacity_budget(task_type: str) -> dict[str, Any]:
    capacity = dev_swarm_scheduler.capacity_status()
    recommendation = capacity.get("recommendation") or {}
    admittable = int(recommendation.get("admittable_now") or 0)
    coding = int(recommendation.get("coding_inference") or 0)
    if task_type == "voice":
        return {"ok": True, "admittable_now": max(1, admittable), "capacity": capacity}
    allowed = min(admittable, DEFAULT_GENERATION_SLOTS, coding or DEFAULT_GENERATION_SLOTS)
    return {"ok": allowed > 0, "admittable_now": allowed, "capacity": capacity}


def acquire_gpu_inference_lease(
    *,
    agent: str,
    task_id: str,
    task_type: str = "coding",
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    slot: int = 0,
) -> dict[str, Any]:
    """Acquire a shared GPU generation lease or return queued/backpressure."""
    budget = _capacity_budget(task_type)
    if not budget.get("ok"):
        return {
            "ok": False,
            "error": "gpu_capacity_zero",
            "queued": True,
            "admittable_now": budget.get("admittable_now", 0),
            "capacity": budget.get("capacity"),
        }

    node = _node_id()
    resource_id = _generation_resource_id(node, slot=slot)
    decision = racb_locks.manage_coordination_lock(
        action="acquire",
        resource_id=resource_id,
        agent=(agent or "").strip().lower(),
        task_id=task_id,
        ttl_seconds=ttl_seconds,
    )
    if not decision.get("ok"):
        error = str(decision.get("error") or "gpu_inference_lease_denied")
        return {
            "ok": False,
            "error": error,
            "queued": error == "lock_conflict",
            "resource_id": resource_id,
            "capacity": budget.get("capacity"),
            "lock": decision,
        }
    return {
        "ok": True,
        "resource_lease_id": resource_id,
        "resource_id": resource_id,
        "node": node,
        "slot": slot,
        "capacity": budget.get("capacity"),
        "lock": decision,
    }


def release_gpu_inference_lease(
    *,
    agent: str,
    task_id: str,
    resource_lease_id: str,
) -> dict[str, Any]:
    resource_id = str(resource_lease_id or "").strip()
    if not resource_id:
        return {"ok": True, "released": False, "idempotent": True}
    return racb_locks.manage_coordination_lock(
        action="release",
        resource_id=resource_id,
        agent=(agent or "").strip().lower(),
        task_id=task_id,
    )
