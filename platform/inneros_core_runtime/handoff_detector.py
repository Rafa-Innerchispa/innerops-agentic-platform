"""Detecta handoffs faltantes — tareas abiertas sin cierre de agente."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.settings import COL_AGENT_ACTIVITY, COL_ORCHESTRATION_TASKS


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def detect_missing_handoff(hours: int = 48) -> dict[str, Any]:
    """Marca tareas dispatched/in_progress sin actividad completed reciente."""
    db = mongo_store.get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 168)))
    flags: list[dict[str, Any]] = []

    open_tasks = db[COL_ORCHESTRATION_TASKS].find(
        {"status": {"$in": ["dispatched", "in_progress", "pending"]}}
    )
    for task in open_tasks:
        tid = str(task["_id"])
        agent = task.get("target_agent", "")
        created = _parse_ts(task.get("created_at") or task.get("updated_at"))
        if created and created > cutoff:
            continue
        completed = db[COL_AGENT_ACTIVITY].find_one(
            {"task_id": tid, "status": "completed", "agent": agent}
        )
        if not completed:
            flags.append(
                {
                    "kind": "orchestration_task",
                    "task_id": tid,
                    "agent": agent,
                    "title": task.get("title", ""),
                    "status": task.get("status"),
                    "since": task.get("created_at"),
                    "severity": "high" if task.get("priority") == "high" else "normal",
                }
            )

    for agent in ("CURSOR", "CODEX", "ANTIGRAVITY"):
        started = list(
            db[COL_AGENT_ACTIVITY].find(
                {"agent": agent, "status": "started"},
            ).sort("started_at", -1).limit(10)
        )
        for act in started:
            aid = str(act.get("_id", ""))
            task_id = act.get("task_id", "")
            started_at = _parse_ts(act.get("started_at") or act.get("updated_at"))
            if started_at and started_at > cutoff:
                continue
            finish = db[COL_AGENT_ACTIVITY].find_one(
                {
                    "agent": agent,
                    "$or": [
                        {"task_id": task_id, "status": {"$in": ["completed", "failed"]}},
                        {"_id": act["_id"], "status": {"$in": ["completed", "failed"]}},
                    ],
                }
            )
            if not finish:
                flags.append(
                    {
                        "kind": "agent_activity",
                        "activity_id": aid,
                        "agent": agent,
                        "summary": act.get("summary", ""),
                        "since": act.get("started_at"),
                        "severity": "normal",
                    }
                )

    mongo_store.log_coordination(
        agent="WATCHDOG",
        summary=f"Missing handoff scan: {len(flags)} flags",
        event="missing_handoff_scan",
        project="ralfia-orchestration",
        metadata={"count": len(flags)},
    )
    return {"ok": True, "count": len(flags), "flags": flags[:50], "hours_window": hours}
