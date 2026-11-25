"""Notificaciones ntfy de ciclo de vida OPS (inicio, fallo, terminada, atascada)."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.notifications import inneros_ntfy_client as ntfy
from inneros_core_runtime.notifications import inneros_owner_message as msgfmt
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
    "authorized_pending_peer": ("Autorizada — otro servidor", "default", ["hourglass"]),
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


def _dedupe_seen(task_id: str, event: str, *, force: bool = False) -> bool:
    if force or not task_id:
        return False
    from raphiia_openai import mongo_store

    col = mongo_store.get_db()["ralfia_owner_push_dedupe"]
    key = f"{task_id}:{event}"
    if col.find_one({"_id": key}):
        return True
    col.insert_one({"_id": key, "task_id": task_id, "event": event, "created_at": __import__("time").time()})
    return False


def notify_lifecycle(
    task: dict[str, Any],
    *,
    event: str,
    detail: str = "",
    previous_status: str = "",
    force: bool = False,
) -> dict[str, Any]:
    if not LIFECYCLE_ON() or not ntfy.configured():
        return {"ok": False, "skipped": "inneros_lifecycle_off"}
    ev = (event or "").strip().lower() or str(task.get("status") or "update").lower()
    tid = str(task.get("task_id") or "")
    if _dedupe_seen(tid, ev, force=force):
        return {"ok": False, "skipped": "duplicate_lifecycle", "task_id": tid, "event": ev}
    label, priority, tags = EVENT_LABELS.get(ev, ("OPS", "default", ["bell"]))
    alias = msgfmt.task_code(task)
    provider = str(task.get("assignee") or task.get("preferred_provider") or "?").upper()
    if previous_status:
        detail = (detail + f"\nTransición: {previous_status} → {task.get('status', ev)}").strip()
    title, msg = msgfmt.format_owner_push(task, event=ev, detail=detail)
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