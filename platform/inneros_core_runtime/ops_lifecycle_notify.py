"""Owner lifecycle WhatsApp for ops tasks (dedupe via Mongo revision)."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.notifications.evolution_client import send_alert_whatsapp

NOTIFY = os.getenv("NOTIFY_OPS_TASKS", "1") == "1"
NOTIFY_START = os.getenv("NOTIFY_OPS_WORKER_STARTED", "1") == "1"
NOTIFY_STALL = os.getenv("NOTIFY_OPS_STALLED", "1") == "1"


def _is_test_task(task: dict[str, Any]) -> bool:
    title = str(task.get("title") or "").upper()
    tags = task.get("tags") or []
    return "TEST" in title or "CONCURRENCY_E2E" in title or "concurrency_e2e" in tags


def _prefix(task: dict[str, Any]) -> str:
    return "[TEST] " if _is_test_task(task) else ""


def _already_sent(task: dict[str, Any], token: str) -> bool:
    sent = task.get("lifecycle_notifications") or []
    return token in sent


def _mark_sent(task_id: str, token: str) -> None:
    mongo_store.get_db()[OPS_TASKS_COL].update_one(
        {"task_id": task_id},
        {"$addToSet": {"lifecycle_notifications": token}},
    )


def notify_ops_worker_started(task: dict[str, Any], *, worker: dict[str, Any] | None = None) -> dict[str, Any]:
    if not NOTIFY or not NOTIFY_START:
        return {"ok": False, "skipped": "disabled"}
    tid = str(task.get("task_id") or "")
    rev = int(task.get("revision") or 0)
    token = f"owner_worker_started:{tid}:r{rev}"
    if _already_sent(task, token):
        return {"ok": False, "skipped": "dedupe", "token": token}
    wid = str((worker or {}).get("worker_id") or task.get("worker_id") or "?")
    host = str((worker or {}).get("node") or task.get("worker_host") or "?")
    body = (
        f"{_prefix(task)}▶️ OPS START (worker real)\n"
        f"`{tid}`\n"
        f"{str(task.get('title') or '')[:90]}\n"
        f"Worker: {wid} · Host: {host}\n"
        f"{ralfia_time.format_log()}"
    )
    wa = send_alert_whatsapp(body, prefix_node=True)
    if wa.get("ok"):
        _mark_sent(tid, token)
    return {"ok": bool(wa.get("ok")), "whatsapp": wa, "token": token}


def notify_ops_stalled_or_failed(
    task: dict[str, Any],
    *,
    reason: str,
    target_status: str = "blocked",
) -> dict[str, Any]:
    if not NOTIFY or not NOTIFY_STALL:
        return {"ok": False, "skipped": "disabled"}
    tid = str(task.get("task_id") or "")
    rev = int(task.get("revision") or 0)
    token = f"owner_{target_status}:{tid}:{reason}:r{rev}"
    if _already_sent(task, token):
        return {"ok": False, "skipped": "dedupe", "token": token}
    icon = "⏱️" if "stall" in reason else "❌"
    body = (
        f"{_prefix(task)}{icon} OPS {target_status.upper()}\n"
        f"`{tid}`\n"
        f"Motivo: {reason[:400]}\n"
        f"{ralfia_time.format_log()}"
    )
    wa = send_alert_whatsapp(body, prefix_node=True)
    if wa.get("ok"):
        _mark_sent(tid, token)
    return {"ok": bool(wa.get("ok")), "whatsapp": wa, "token": token}
