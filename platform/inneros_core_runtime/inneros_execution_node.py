"""Etiqueta de nodo de ejecución (Intel vs AMD) para pushes y diagnóstico."""

from __future__ import annotations

from typing import Any

from inneros_core_runtime import cursor_headless_lanes as lanes

_ROLE_LABEL = {"intel": "Intel", "amd": "AMD", "primary": "Intel", "secondary": "AMD", "gpu_worker": "AMD"}


def role_from_hostname(hostname: str) -> str:
    h = (hostname or "").strip().lower()
    if not h:
        return lanes.node_role()
    if any(token in h for token in lanes.HOST_INTEL) or h.startswith("ralphi-ia") or "-ia-" in h:
        return "intel"
    if any(token in h for token in lanes.HOST_AMD) or "amd" in h:
        return "amd"
    return lanes.node_role()


def node_display(task: dict[str, Any] | None = None) -> tuple[str, str]:
    """Returns (human_label, hostname) e.g. ('Intel', 'ralphi-ia')."""
    role = lanes.node_role()
    host = lanes.hostname()
    if task:
        host_key = (
            task.get("claim_execution_role")
            or task.get("cursor_execution_role")
            or task.get("headless_execution_role")
        )
        if isinstance(host_key, str) and host_key.strip():
            role = host_key.strip().lower()
        for key in ("headless_execution_host", "provider_execution_host", "claim_host"):
            h = task.get(key)
            if h:
                host = str(h).strip()
                role = role_from_hostname(host)
                break
    label = _ROLE_LABEL.get(role, role.upper() if role else "?")
    return label, host


def format_taken_by(task: dict[str, Any] | None = None) -> str:
    label, host = node_display(task)
    return f"Tarea tomada por {label} ({host})"