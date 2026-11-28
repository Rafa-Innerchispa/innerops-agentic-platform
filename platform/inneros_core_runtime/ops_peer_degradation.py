"""Intel takeover when AMD peer is down — explicit degraded cluster mode (not silent failover)."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store, ralfia_time

COORD_KEY = "cluster_degradation_mode"


def _env_truthy(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def auto_steer_enabled() -> bool:
    return _env_truthy("INNEROS_INTEL_DEGRADATION_AUTO_STEER", "1")


def peer_alive(role: str, *, ttl_seconds: int = 300) -> bool:
    role = (role or "").strip().lower()
    if role == "amd":
        from inneros_core_runtime import cursor_headless_lanes as chl

        return chl.peer_is_alive(ttl_seconds=ttl_seconds)
    if role == "intel":
        from inneros_core_runtime import cursor_headless_lanes as chl

        row = mongo_store.get_coordination_state("cursor_node_liveness_intel")
        state = (row.get("state") or {}) if row.get("ok") else {}
        ts = state.get("last_seen_at")
        if not ts:
            return chl.node_role() == "intel"
        return chl.peer_is_alive(ttl_seconds=ttl_seconds) or chl.node_role() == "intel"
    return False


def degradation_snapshot(*, ttl_seconds: int = 300) -> dict[str, Any]:
    from inneros_core_runtime import cursor_headless_lanes as chl

    here = chl.node_role()
    amd_up = peer_alive("amd", ttl_seconds=ttl_seconds)
    intel_up = peer_alive("intel", ttl_seconds=ttl_seconds) or here == "intel"
    active = (
        auto_steer_enabled()
        and here == "intel"
        and intel_up
        and not amd_up
    ) or _env_truthy("INNEROS_PEER_DEGRADATION_FORCE", "0")
    mode = "normal" if amd_up and intel_up else ("degraded_intel_primary" if active else "partitioned")
    snap = {
        "mode": mode,
        "degradation_active": active,
        "local_role": here,
        "amd_peer_alive": amd_up,
        "intel_peer_alive": intel_up,
        "auto_steer": auto_steer_enabled(),
        "updated_at": ralfia_time.now_utc_iso(),
        "note": (
            "AMD offline: OPS steering to Intel for non-GPU tasks; Mongo/coordination on Intel."
            if active
            else "Dual-node or steering disabled."
        ),
    }
    mongo_store.upsert_coordination_state(key=COORD_KEY, data=snap)
    return snap


def task_explicit_amd_only(task: dict[str, Any]) -> bool:
    """Owner text that forbids Intel failover (e.g. MSP node proof on 192.168.1.5)."""
    blob = " ".join(
        [
            str(task.get("objective") or ""),
            str(task.get("title") or ""),
            str((task.get("payload") or {}).get("verify_command") or ""),
        ]
    ).lower()
    markers = (
        "solamente amd",
        "solo amd",
        "only amd",
        "nunca intel",
        "never intel",
        "host_mismatch",
        "192.168.1.5",
        "ralfiia-amd",
    )
    return any(m in blob for m in markers)


def task_requires_amd_gpu(task: dict[str, Any]) -> bool:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    if payload.get("requires_amd_gpu") is True:
        return True
    if str(payload.get("execution_profile") or "").strip().lower() in {"gpu", "amd_gpu", "qwen_local"}:
        return True
    if payload.get("requires_gpu") or payload.get("gpu_only") or payload.get("vllm_required"):
        return True
    model = str(task.get("preferred_model") or payload.get("preferred_model") or "").lower()
    lane = str(task.get("execution_lane") or "").lower()
    if any(m in model for m in ("qwen", "vllm")):
        return True
    if "qwen" in lane or "vllm" in lane or "gpu" in lane:
        return True
    objective = str(task.get("objective") or task.get("title") or "").lower()
    if any(
        phrase in objective
        for phrase in (
            "vllm",
            "qwen/",
            "qwen2",
            "qwen3",
            "32b",
            "local model on amd",
            "solo gpu",
            "solo en amd gpu",
        )
    ):
        return True
    if payload.get("local_model_router_lane") in {"amd_qwen", "amd_vllm", "gpu_worker"}:
        return True
    return False


def degradation_active_local(*, ttl_seconds: int = 300) -> bool:
    from inneros_core_runtime import cursor_headless_lanes as chl

    if _env_truthy("INNEROS_PEER_DEGRADATION_FORCE", "0"):
        return chl.node_role() == "intel"
    if not auto_steer_enabled() or chl.node_role() != "intel":
        return False
    return not peer_alive("amd", ttl_seconds=ttl_seconds)


def allow_intel_steering(task: dict[str, Any]) -> bool:
    if not degradation_active_local():
        return False
    if task_requires_amd_gpu(task) or task_explicit_amd_only(task):
        return False
    from inneros_core_runtime import cursor_headless_lanes as chl

    if chl.node_role() != "intel":
        return False
    pref = chl.task_prefers_other_node(task)
    return pref == "amd"


def fail_closed_relaxed(task: dict[str, Any]) -> bool:
    """When True, do not block claim/execute on Intel despite amd pin + fail_closed flag."""
    return allow_intel_steering(task)


def steer_task_to_intel(task: dict[str, Any], *, actor: str = "peer_degradation") -> dict[str, Any]:
    tid = str(task.get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    if task_requires_amd_gpu(task):
        return {"ok": False, "error": "amd_gpu_required", "task_id": tid}
    if task_explicit_amd_only(task):
        return {"ok": False, "error": "amd_explicit_only", "task_id": tid}
    payload = dict(task.get("payload") or {})
    payload.update(
        {
            "target_node": "intel",
            "execution_node": "intel",
            "owner_execution_node": "intel",
            "preferred_execution_host": "intel",
            "execution_node_resolved": "intel",
            "execution_node_resolved_reason": f"peer_degradation:{actor}",
            "fail_closed_on_node_mismatch": False,
            "degradation_steered_from": str(task.get("target_execution_node") or "amd"),
            "degradation_steered_at": ralfia_time.now_utc_iso(),
        }
    )
    patch: dict[str, Any] = {
        "target_execution_node": "intel",
        "preferred_execution_host": "intel",
        "owner_execution_node": "intel",
        "payload": payload,
        "cluster_degradation_mode": "degraded_intel_primary",
        "updated_at": ralfia_time.now_utc_iso(),
    }
    db = mongo_store.get_db()
    db[OPS_TASKS_COL].update_one({"task_id": tid}, {"$set": patch, "$inc": {"revision": 1}})
    return {"ok": True, "task_id": tid, "target_node": "intel", "reason": "peer_degradation"}


def reconcile_amd_tasks_to_intel(*, limit: int = 40) -> dict[str, Any]:
    snap = degradation_snapshot()
    if not snap.get("degradation_active"):
        return {"ok": True, "skipped": "degradation_inactive", "snapshot": snap}
    statuses = {
        "queued",
        "awaiting_cursor_claim",
        "awaiting_codex_claim",
        "awaiting_antigravity_claim",
        "awaiting_gemini_claim",
        "awaiting_owner_auth",
        "awaiting_owner_authorization",
        "claimed",
        "in_progress",
        "blocked",
    }
    db = mongo_store.get_db()
    moved: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for task in (
        db[OPS_TASKS_COL]
        .find(
            {
                "status": {"$in": sorted(statuses)},
                "$or": [
                    {"target_execution_node": "amd"},
                    {"preferred_execution_host": "amd"},
                    {"payload.execution_node_resolved": "amd"},
                ],
            },
            {"_id": 0},
        )
        .sort("updated_at", -1)
        .limit(max(1, min(int(limit), 100)))
    ):
        tid = str(task.get("task_id") or "")
        if task_requires_amd_gpu(task):
            blocked.append({"task_id": tid, "reason": "amd_gpu_required"})
            continue
        if task_explicit_amd_only(task):
            blocked.append({"task_id": tid, "reason": "amd_explicit_only"})
            continue
        if str(task.get("target_execution_node") or "").lower() == "intel":
            continue
        moved.append(steer_task_to_intel(task))
    return {
        "ok": True,
        "snapshot": snap,
        "steered": moved,
        "blocked_gpu": blocked,
        "count_steered": len(moved),
    }