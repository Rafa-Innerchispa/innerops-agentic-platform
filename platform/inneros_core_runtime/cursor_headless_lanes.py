"""HA dual-node Cursor headless lanes (AMD + Intel), concurrency and peer liveness."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store

PEERS = ("amd", "intel")
HOST_AMD = ("ralfiia-amd", "amd")
HOST_INTEL = ("ralfiia-intel", "intel", "ralphi-ia-ver-10", "ralphi-ia")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hostname() -> str:
    return socket.gethostname().lower()


def node_role() -> str:
    role = (os.getenv("INNEROS_NODE_ROLE") or "").strip().lower()
    if role in {"amd", "intel", "gpu_worker", "secondary", "primary"}:
        if role == "gpu_worker":
            return "amd"
        if role in {"secondary", "primary"}:
            return role if role in PEERS else "amd"
        return role
    h = hostname()
    if any(token in h for token in HOST_INTEL) or h.startswith("ralphi-ia") or "-ia-" in h:
        return "intel"
    if any(token in h for token in HOST_AMD) or "amd" in h:
        return "amd"
    return "amd"


def is_ha_execution_node() -> bool:
    if os.getenv("INNEROS_CURSOR_HA_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return node_role() in PEERS or "ralfiia" in hostname()


def max_concurrent() -> int:
    raw = int(os.getenv("INNEROS_CURSOR_MAX_CONCURRENT", "2"))
    ceiling = int(os.getenv("INNEROS_CURSOR_MAX_CONCURRENT_CEILING", "8"))
    return max(1, min(raw, ceiling))


def machine_name() -> str:
    return (os.getenv("INNEROS_CURSOR_MACHINE_NAME") or hostname()).strip()


def touch_node_liveness() -> dict[str, Any]:
    role = node_role()
    payload = {
        "role": role,
        "host": hostname(),
        "machine_name": machine_name(),
        "max_concurrent": max_concurrent(),
        "last_seen_at": _now(),
    }
    mongo_store.upsert_coordination_state(key=f"cursor_node_liveness_{role}", data=payload)
    return payload


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def peer_role() -> str:
    return "intel" if node_role() == "amd" else "amd"


def peer_is_alive(*, ttl_seconds: int = 300) -> bool:
    row = mongo_store.get_coordination_state(f"cursor_node_liveness_{peer_role()}")
    state = (row.get("state") or {}) if row.get("ok") else {}
    ts = _parse_ts(state.get("last_seen_at"))
    if not ts:
        return False
    return (datetime.now(timezone.utc) - ts).total_seconds() <= ttl_seconds


def task_prefers_other_node(task: dict[str, Any]) -> str | None:
    payload = dict(task.get("payload") or {})
    pref = (
        str(
            payload.get("preferred_execution_host")
            or payload.get("execution_host")
            or payload.get("target_node")
            or task.get("preferred_execution_host")
            or task.get("execution_host")
            or task.get("target_node")
            or ""
        )
        .strip()
        .lower()
    )
    if pref in {"amd", "intel", "ralfiia-amd", "ralfiia-intel"}:
        if "intel" in pref:
            return "intel"
        if "amd" in pref:
            return "amd"
    return None


def should_this_node_run_task(task: dict[str, Any]) -> tuple[bool, str]:
    """Return (allowed, reason) for claiming/executing on this node."""
    if not is_ha_execution_node():
        return False, "ha_disabled_or_unknown_host"
    pref = task_prefers_other_node(task)
    here = node_role()
    if pref and pref != here:
        if peer_is_alive():
            return False, f"preferred_peer_alive:{pref}"
        return True, f"peer_offline_steering_from_{pref}"
    return True, "local_ok"


def active_lane_count(*, host: str | None = None) -> int:
    h = (host or hostname()).lower()
    db = mongo_store.get_db()
    filt = {
        "assignee": "cursor",
        "status": {"$in": ["in_progress", "claimed", "running"]},
        "headless_execution_started_at": {"$exists": True},
        "headless_execution_finished_at": {"$exists": False},
        "$or": [
            {"headless_execution_host": h},
            {"headless_execution_host": {"$regex": h.split(".")[0], "$options": "i"}},
        ],
    }
    return db[OPS_TASKS_COL].count_documents(filt)


def available_slots() -> int:
    return max(0, max_concurrent() - active_lane_count())


def lane_status() -> dict[str, Any]:
    here = node_role()
    peer = peer_role()
    return {
        "ok": True,
        "host": hostname(),
        "role": here,
        "peer_role": peer,
        "peer_alive": peer_is_alive(),
        "max_concurrent": max_concurrent(),
        "active_lanes": active_lane_count(),
        "available_slots": available_slots(),
        "machine_name": machine_name(),
    }
