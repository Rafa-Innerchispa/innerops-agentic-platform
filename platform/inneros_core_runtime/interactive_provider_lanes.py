"""Dual-node interactive lanes for Codex / Antigravity (1 slot per provider per node)."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime import cursor_headless_lanes as cursor_lanes
from raphiia_openai import mongo_store

SUPPORTED = frozenset({"codex", "antigravity"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hostname() -> str:
    return socket.gethostname().lower()


def node_role() -> str:
    return cursor_lanes.node_role()


def max_concurrent(provider: str) -> int:
    prov = (provider or "").strip().lower()
    if prov not in SUPPORTED:
        return 0
    raw = int(os.getenv(f"INNEROS_{prov.upper()}_MAX_CONCURRENT", "1"))
    ceiling = int(os.getenv(f"INNEROS_{prov.upper()}_MAX_CONCURRENT_CEILING", "2"))
    return max(0, min(raw, ceiling))


def touch_node_liveness(provider: str) -> dict[str, Any]:
    prov = (provider or "").strip().lower()
    role = node_role()
    payload = {
        "provider": prov,
        "role": role,
        "host": hostname(),
        "max_concurrent": max_concurrent(prov),
        "last_seen_at": _now(),
    }
    mongo_store.upsert_coordination_state(key=f"{prov}_node_liveness_{role}", data=payload)
    return payload


def peer_is_alive(provider: str, *, ttl_seconds: int = 300) -> bool:
    prov = (provider or "").strip().lower()
    peer = cursor_lanes.peer_role()
    row = mongo_store.get_coordination_state(f"{prov}_node_liveness_{peer}")
    state = (row.get("state") or {}) if row.get("ok") else {}
    ts_raw = state.get("last_seen_at")
    if not ts_raw:
        return False
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - ts).total_seconds() <= ttl_seconds


def should_this_node_run_task(provider: str, task: dict[str, Any]) -> tuple[bool, str]:
    prov = (provider or "").strip().lower()
    if prov not in SUPPORTED:
        return False, "unsupported_provider"
    allowed, reason = cursor_lanes.should_this_node_run_task(task)
    if not allowed:
        return allowed, reason
    pref = cursor_lanes.task_prefers_other_node(task)
    here = node_role()
    if pref and pref != here and peer_is_alive(prov):
        return False, f"preferred_peer_alive:{pref}"
    return True, "local_ok"


def active_lane_count(provider: str, *, host: str | None = None) -> int:
    prov = (provider or "").strip().lower()
    h = (host or hostname()).lower()
    db = mongo_store.get_db()
    filt = {
        "assignee": prov,
        "status": {"$in": ["in_progress", "claimed", "running", "verification"]},
        "provider_execution_started_at": {"$exists": True},
        "provider_execution_finished_at": {"$exists": False},
        "$or": [
            {"provider_execution_host": h},
            {"provider_execution_host": {"$regex": h.split(".")[0], "$options": "i"}},
        ],
    }
    return db[OPS_TASKS_COL].count_documents(filt)


def available_slots(provider: str) -> int:
    return max(0, max_concurrent(provider) - active_lane_count(provider))


def lane_status(provider: str) -> dict[str, Any]:
    prov = (provider or "").strip().lower()
    here = node_role()
    peer = cursor_lanes.peer_role()
    return {
        "ok": True,
        "provider": prov,
        "host": hostname(),
        "role": here,
        "peer_role": peer,
        "peer_alive": peer_is_alive(prov),
        "max_concurrent": max_concurrent(prov),
        "active_lanes": active_lane_count(prov),
        "available_slots": available_slots(prov),
    }
