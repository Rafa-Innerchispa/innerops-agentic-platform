"""Enrutamiento Intel/AMD para OPS: owner elige nodo, default Antigravity→Intel, failover HA."""

from __future__ import annotations

import os
import random
from datetime import datetime, timezone
from typing import Any

from inneros_core_runtime import cursor_headless_lanes as chl
from inneros_core_runtime import interactive_provider_lanes as ipl
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store

_NODE_ALIASES_INTEL = frozenset(
    {"intel", "ia", "primary", "ralfiia-intel", "ralphi-ia", "inneros-intel", "1.4", "local-intel-4"}
)
_NODE_ALIASES_AMD = frozenset(
    {"amd", "gpu", "secondary", "ralfiia-amd", "gpu_worker", "1.5", "local-amd-5", "192.168.1.5"}
)
_NODE_AUTO = frozenset({"auto", "balancer", "balance", "ha", "any", "random"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_node(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in _NODE_ALIASES_INTEL or "intel" in raw:
        return "intel"
    if raw in _NODE_ALIASES_AMD or raw == "amd":
        return "amd"
    if raw in _NODE_AUTO:
        return "auto"
    return None


def _routing_keys(task: dict[str, Any]) -> list[tuple[str, Any]]:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    out: list[tuple[str, Any]] = []
    for key in (
        "owner_execution_node",
        "execution_node",
        "target_node",
        "preferred_execution_host",
        "execution_host",
    ):
        if key in payload:
            out.append((f"payload.{key}", payload.get(key)))
        if key in task:
            out.append((key, task.get(key)))
    return out


def default_node_for_provider(provider: str) -> str:
    prov = (provider or "").strip().lower()
    if prov == "antigravity":
        return normalize_node(os.getenv("INNEROS_ANTIGRAVITY_DEFAULT_EXECUTION_NODE", "intel")) or "intel"
    return normalize_node(os.getenv("INNEROS_DEFAULT_EXECUTION_NODE", "intel")) or "intel"


def pick_balanced_node(provider: str) -> str:
    """Elige nodo con más slots libres; si empate, Antigravity default Intel."""
    prov = (provider or "").strip().lower()
    here = chl.node_role()
    peer = chl.peer_role()
    slots_here = ipl.available_slots(prov) if prov in {"codex", "antigravity"} else chl.available_slots()
    peer_alive = ipl.peer_is_alive(prov) if prov in {"codex", "antigravity"} else chl.peer_is_alive()
    if not peer_alive:
        return here
    if slots_here > 0:
        return here
    return peer if peer else default_node_for_provider(prov)


def resolve_target_node(task: dict[str, Any], provider: str) -> tuple[str, str]:
    for src, raw in _routing_keys(task):
        node = normalize_node(raw)
        if not node:
            continue
        if node == "auto":
            picked = pick_balanced_node(provider)
            return picked, f"{src}:auto→{picked}"
        return node, src
    default = default_node_for_provider(provider)
    return default, f"provider_default:{default}"


def stamp_routing_on_task(task_id: str, *, provider: str | None = None) -> dict[str, Any]:
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or {}
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": task_id}
    prov = (provider or task.get("assignee") or task.get("preferred_provider") or "").strip().lower()
    target, reason = resolve_target_node(task, prov)
    payload = dict(task.get("payload") or {})
    payload["preferred_execution_host"] = target
    payload["execution_node_resolved"] = target
    payload["execution_node_resolved_reason"] = reason
    patch = {
        "preferred_execution_host": target,
        "target_execution_node": target,
        "execution_node_resolved_at": _now(),
        "execution_node_resolved_reason": reason,
        "updated_at": _now(),
        "payload": payload,
    }
    db[OPS_TASKS_COL].update_one({"task_id": task_id}, {"$set": patch})
    return {"ok": True, "task_id": task_id, "target_node": target, "reason": reason}


def should_claim_on_this_node(task: dict[str, Any], provider: str) -> tuple[bool, str, str]:
    """(allowed, reason, target_node) — si no, el peer debe reclamar."""
    target, _ = resolve_target_node(task, provider)
    prov = (provider or "").strip().lower()
    here = chl.node_role()
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    owner_pick = normalize_node(payload.get("owner_execution_node") or "")
    if owner_pick and owner_pick != "auto" and target != here:
        return False, f"explicit_owner_node:{target}", target
    if prov in {"codex", "antigravity"}:
        allowed, reason = ipl.should_this_node_run_task(prov, task)
        return allowed, reason, target
    allowed, reason = chl.should_this_node_run_task(task)
    return allowed, reason, target


def describe_routing(task: dict[str, Any], *, event: str = "") -> str:
    from inneros_core_runtime import inneros_execution_node as ien

    target = str(
        task.get("target_execution_node")
        or (task.get("payload") or {}).get("execution_node_resolved")
        or (task.get("payload") or {}).get("preferred_execution_host")
        or ""
    ).strip()
    label, host = ien.node_display(task)
    tlabel = {"intel": "Intel", "amd": "AMD"}.get(target.lower(), target.upper() if target else "")
    if event in ("auth_request", "authorized", "authorized_pending_claim", "authorized_pending_peer"):
        if tlabel:
            return f"Nodo previsto para ejecutar: {tlabel}"
        return f"Nodo previsto: {default_node_for_provider(str(task.get('assignee') or ''))}"
    if tlabel and tlabel != label:
        return f"Ejecutando en {label} ({host}) · Objetivo era {tlabel}"
    if event in ("claimed", "in_progress", "running"):
        prov = str(task.get("assignee") or "?").strip().upper()
        return f"Ejecutando en {label} ({host}) · Agente {prov}"
    return ien.format_taken_by(task)