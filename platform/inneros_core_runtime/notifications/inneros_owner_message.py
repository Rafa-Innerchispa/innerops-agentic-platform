"""Plantillas claras para pushes owner (ID único, quién, qué, estado)."""

from __future__ import annotations

from typing import Any


def task_code(task: dict[str, Any]) -> str:
    return str(
        task.get("human_task_id")
        or task.get("task_alias")
        or task.get("correlation_id")
        or task.get("task_id")
        or "?"
    )


def format_owner_push(
    task: dict[str, Any],
    *,
    event: str,
    headline: str = "",
    detail: str = "",
) -> tuple[str, str]:
    """Returns (title, body) for ntfy."""
    code = task_code(task)
    provider = str(task.get("assignee") or task.get("preferred_provider") or "?").upper()
    from_agent = str(task.get("from_agent") or "InnerOS").strip()
    title_raw = str(task.get("title") or headline or "OPS").strip()
    obj = str(task.get("objective") or detail or "").strip()
    ev_label = {
        "auth_request": "Autorización requerida",
        "authorized": "Autorizada",
        "authorized_pending_claim": "Autorizada — esperando agente",
        "claimed": "Tarea iniciada (claim)",
        "in_progress": "En ejecución",
        "running": "En ejecución",
        "completed": "Terminada",
        "failed": "Falló",
        "blocked": "Bloqueada",
        "cancelled": "Cancelada",
        "stalled": "Sin avance (revisar)",
        "verification": "En verificación",
    }.get(event, headline or event)

    title = f"{provider} · {ev_label}"
    lines = [
        f"ID: {code}",
        f"Tarea: {title_raw[:220]}",
        f"Agente: {provider} · Origen: {from_agent}",
    ]
    if obj:
        lines.append(f"Detalle: {obj[:400]}")
    if detail and detail not in obj:
        lines.append(str(detail)[:400])
    if ev_label in {
        "Tarea iniciada (claim)",
        "En ejecución",
        "Ejecutando",
        "Tarea en curso",
    } or event in ("claimed", "in_progress", "running"):
        try:
            from inneros_core_runtime import inneros_execution_node as ien

            node_line = ien.format_taken_by(task)
            if node_line not in "\n".join(lines):
                lines.append(node_line)
        except Exception:
            pass
    lines.append(f"Estado: {ev_label}")
    return title[:120], "\n".join(lines)[:3800]