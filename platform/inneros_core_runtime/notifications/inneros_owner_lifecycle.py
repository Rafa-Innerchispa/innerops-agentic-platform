"""Notificaciones ntfy de ciclo de vida OPS (inicio, fallo, terminada, atascada)."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.notifications import inneros_ntfy_client as ntfy
from inneros_core_runtime.owner_push_tokens import public_base_url

LIFECYCLE_ON = lambda: os.getenv("NOTIFY_OPS_INNEROS_LIFECYCLE", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

EVENT_LABELS = {
    "authorized": ("Autorizada", "high", ["white_check_mark"]),
    "authorized_pending_claim": ("Autorizada — esperando IDE", "default", ["hourglass"]),
    "claimed": ("Tarea en curso", "default", ["arrow_forward"]),
    "in_progress": ("Ejecutando", "default", ["hourglass_flowing_sand"]),
    "completed": ("Terminada", "default", ["white_check_mark"]),
    "failed": ("Falló", "high", ["x"]),
    "blocked": ("Bloqueada", "high", ["no_entry"]),
    "cancelled": ("Cancelada", "low", ["no_entry_sign"]),
    "stalled": ("Atascada / sin avance", "high", ["warning"]),
    "verification": ("En verificación", "default", ["mag"]),
}


def _click(task_id: str) -> str:
    return f"{public_base_url()}/owner-ops/?task_id={task_id}"


def notify_lifecycle(
    task: dict[str, Any],
    *,
    event: str,
    detail: str = "",
    previous_status: str = "",
) -> dict[str, Any]:
    if not LIFECYCLE_ON() or not ntfy.configured():
        return {"ok": False, "skipped": "inneros_lifecycle_off"}
    ev = (event or "").strip().lower() or str(task.get("status") or "update").lower()
    label, priority, tags = EVENT_LABELS.get(ev, ("OPS", "default", ["bell"]))
    tid = str(task.get("task_id") or "")
    alias = str(task.get("human_task_id") or task.get("task_alias") or tid)
    provider = str(task.get("assignee") or task.get("preferred_provider") or "?").upper()
    title = f"{provider} · {label}"
    lines = [alias]
    if detail:
        lines.append(detail[:500])
    elif task.get("title"):
        lines.append(str(task.get("title"))[:280])
    if previous_status:
        lines.append(f"Antes: {previous_status} → {task.get('status', ev)}")
    msg = "\n".join(lines)
    try:
        from inneros_core_runtime import owner_push_history as inbox

        if tid:
            inbox.record_lifecycle(
                task_id=tid,
                human_task_id=alias,
                provider=provider,
                event=ev,
                title=title,
                message=msg,
            )
    except Exception:
        pass
    return ntfy.publish(
        msg[:3800],
        title=title,
        tags=tags,
        priority=priority,
        click=_click(tid) if tid else "",
        extras={"task_id": tid, "event": ev, "channel": "inneros_lifecycle"},
    )