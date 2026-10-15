"""Project current execution state; preserve historical execution_binding snapshots."""

from __future__ import annotations

from typing import Any

from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store, ralfia_time


def refresh_current_execution_state(
    task: dict[str, Any],
    *,
    event: str,
    actor: str = "system",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = str(task.get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}

    binding = eb.resolve_execution_binding(task)
    summary = eb.owner_execution_summary(task, binding)
    now = ralfia_time.now_utc_iso()
    current = {
        "at": now,
        "event": event,
        "actor": actor,
        "status": task.get("status"),
        "owner_authorized_at": task.get("owner_authorized_at"),
        "claimed_by": task.get("claimed_by"),
        "claimed_at": task.get("claimed_at"),
        "execution_binding": binding,
        "owner_execution_summary": summary,
    }
    if extra:
        current.update(extra)

    db = mongo_store.get_db()
    prev = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"evidence.execution_binding": 1}) or {}
    old_binding = (prev.get("evidence") or {}).get("execution_binding")
    update: dict[str, Any] = {
        "$set": {
            "current_execution_state": current,
            "updated_at": now,
        },
        "$inc": {"revision": 1},
    }
    if old_binding and old_binding != binding:
        update["$push"] = {
            "evidence.execution_binding_history": {
                "at": now,
                "event": event,
                "binding": old_binding,
            }
        }
        update["$set"]["evidence.execution_binding"] = binding
    db[OPS_TASKS_COL].update_one({"task_id": tid}, update)
    return {"ok": True, "task_id": tid, "current_execution_state": current}
