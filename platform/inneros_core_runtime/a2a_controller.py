"""Durable AG-25 consumer for A2A tasks addressed to catalog agents.

The coordination daemon already ticks persistently. This consumer lets AG-25
execute A2A-addressed AG-xx work without requiring an active chat turn.
"""
from __future__ import annotations

import json
import re
from typing import Any

from raphiia_openai import coordination_live, mongo_store

A2A_TITLE_RE = re.compile(r"^\[A2A:(AG-\d{1,2})\]\s*(.*)$", re.IGNORECASE)
TERMINAL = {"completed", "failed", "cancelled", "superseded"}
MAX_RESULT_CHARS = 12000


def _task_message(task: dict[str, Any]) -> str:
    checklist = [str(item) for item in task.get("checklist") or []]
    body = next((item for item in checklist if not item.startswith("A2A ") and item != "Transport=A2A"), "")
    match = A2A_TITLE_RE.match(str(task.get("title") or ""))
    title = match.group(2).strip() if match else str(task.get("title") or "").strip()
    return "\n\n".join(part for part in (title, body) if part).strip()


def _clip_result(result: Any) -> Any:
    try:
        text = json.dumps(result, default=str, ensure_ascii=True)
    except Exception:
        text = str(result)
    if len(text) <= MAX_RESULT_CHARS:
        return result
    return {"truncated": True, "preview": text[:MAX_RESULT_CHARS]}


def _candidate_query() -> dict[str, Any]:
    return {
        "from_agent": "A2A",
        "status": {"$in": ["proposed", "accepted", "in_progress"]},
        "title": {"$regex": r"^\[A2A:AG-\d{1,2}\]", "$options": "i"},
    }


def controller_tick(limit: int = 4, dry_run: bool = False, db: Any | None = None) -> dict[str, Any]:
    """Consume bounded A2A AG-xx tasks through the canonical runner registry."""
    database = db if db is not None else mongo_store.get_db()
    lim = max(1, min(int(limit or 4), 12))
    tasks = list(database[coordination_live.OPS_TASKS_COL].find(_candidate_query(), {"_id": 0}).sort("created_at", 1).limit(lim))
    planned: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        match = A2A_TITLE_RE.match(str(task.get("title") or ""))
        if not task_id or not match:
            continue
        agent_id = match.group(1).upper()
        message = _task_message(task)
        plan = {"task_id": task_id, "agent_id": agent_id, "message_preview": message[:300], "transport": "a2a"}
        planned.append(plan)
        if dry_run:
            continue

        # AG-25 owns the orchestration transition. force_handoff allows recovery
        # of tasks accepted by an earlier daemon instance after a restart.
        try:
            current = database[coordination_live.OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or task
            if str(current.get("status") or "") == "proposed":
                coordination_live.update_ops_task_state(task_id, "accepted", actor="ralfia", force_handoff=True)
            coordination_live.update_ops_task_state(task_id, "in_progress", actor="ralfia", force_handoff=True)
            coordination_live.heartbeat_ops_task(task_id, "ralfia", next_action=f"A2A execute {agent_id}", blocker=None)
        except Exception as exc:
            executed.append({**plan, "ok": False, "error": f"claim_failed:{exc}"})
            continue

        try:
            from raphiia_openai.agents.pool_agent_runners import invoke_agent
            result = invoke_agent(agent_id, message=message, dry_run=False)
        except Exception as exc:
            result = {"ok": False, "agent_id": agent_id, "error": str(exc)}

        ok = bool(isinstance(result, dict) and result.get("ok"))
        evidence = {
            "status": "PASS" if ok else "FAIL",
            "transport": "a2a",
            "controller": "AG-25",
            "target_agent": agent_id,
            "result": _clip_result(result),
        }
        target_status = "completed" if ok else "blocked"
        try:
            coordination_live.update_ops_task_state(task_id, target_status, actor="ralfia", evidence=evidence, force_handoff=True)
        except Exception as exc:
            executed.append({**plan, "ok": False, "error": f"terminal_transition_failed:{exc}", "result": _clip_result(result)})
            continue
        executed.append({**plan, "ok": ok, "status": target_status, "result": _clip_result(result)})

    return {
        "ok": all(item.get("ok", True) for item in executed),
        "controller": "AG-25",
        "transport": "a2a",
        "planned": planned,
        "executed": executed,
        "count": len(executed) if not dry_run else len(planned),
        "dry_run": dry_run,
    }
