"""Plantillas claras para pushes owner (correlación única, nodo, lenguaje humano)."""

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


def correlation_ref(task: dict[str, Any]) -> str:
    """ID estable que debe repetirse en todos los mensajes del mismo trabajo."""
    return str(task.get("correlation_id") or task.get("human_task_id") or task.get("task_id") or "?")


def format_owner_push(
    task: dict[str, Any],
    *,
    event: str,
    headline: str = "",
    detail: str = "",
) -> tuple[str, str]:
    """Returns (title, body) for ntfy."""
    corr = correlation_ref(task)
    short = task_code(task)
    tid = str(task.get("task_id") or "?")
    provider = str(task.get("assignee") or task.get("preferred_provider") or "?").upper()
    from_agent = str(task.get("from_agent") or "sistema InnerOS").strip()
    title_raw = str(task.get("title") or headline or "Trabajo pendiente").strip()
    obj = str(task.get("objective") or "").strip()
    model = str(task.get("effective_model") or task.get("preferred_model") or "").strip()
    ev_label = {
        "auth_request": "Necesitas autorizar",
        "authorized": "Autorizada por ti",
        "authorized_pending_claim": "Autorizada — esperando agente",
        "authorized_pending_peer": "Autorizada — esperando otro servidor",
        "claimed": "Agente tomó la tarea",
        "in_progress": "En ejecución",
        "running": "En ejecución",
        "completed": "Terminada",
        "failed": "Falló",
        "blocked": "Bloqueada",
        "cancelled": "Cancelada",
        "stalled": "Sin avance — revisar",
        "verification": "En verificación",
    }.get(event, headline or event)

    try:
        from inneros_core_runtime import ops_execution_node_routing as oenr

        node_line = oenr.describe_routing(task, event=event)
    except Exception:
        from inneros_core_runtime import inneros_execution_node as ien

        node_line = ien.format_taken_by(task)

    title = f"{tid} · {provider} · {ev_label}"
    if corr and corr != "?" and corr != tid:
        title = f"{tid} · {corr[:36]} · {ev_label}"[:120]

    lines = [
        f"Línea de seguimiento (igual en todos los avisos): {corr}",
    ]
    if short and short != corr:
        lines.append(f"Nombre interno: {short}")
    lines.append(f"Qué es: {title_raw[:200]}")
    lines.append(f"Quién pide: {from_agent} · Agente asignado: {provider}")
    lines.append(node_line)
    if model:
        lines.append(f"Modelo fijado (sin gastar caros): {model}")
    if obj and event == "auth_request":
        lines.append(f"Resumen: {obj[:320]}")
    elif obj and len(obj) < 200:
        lines.append(f"Resumen: {obj}")
    if detail:
        lines.append(detail[:400])
    lines.append(f"Situación ahora: {ev_label}")
    lines.append(f"Código técnico (si soporte lo pide): {tid}")
    return title[:120], "\n".join(lines)[:3800]