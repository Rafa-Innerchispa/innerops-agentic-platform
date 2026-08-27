"""Durable AG-25 consumer for A2A tasks addressed to catalog agents.

The coordination daemon already ticks persistently. This consumer lets AG-25
execute A2A-addressed AG-xx work without requiring an active chat turn.
Each runner is bounded so one slow agent cannot freeze the root orchestrator.

A durable execution lease is written before invoking an agent. If AG-25 or the
outer daemon dies mid-call, a later cycle blocks the expired task instead of
silently invoking it again. This makes A2A execution at-most-once by default.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import coordination_live, mongo_store

A2A_TITLE_RE = re.compile(r"^\[A2A:(AG-\d{1,2})\]\s*(.*)$", re.IGNORECASE)
TERMINAL = {"completed", "failed", "cancelled", "superseded"}
MAX_RESULT_CHARS = 12000
DEFAULT_AGENT_TIMEOUT_SECONDS = 30
A2A_LEASE_GRACE_SECONDS = 5


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


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _execution_lease_state(task: dict[str, Any], timeout_seconds: int, now: datetime | None = None) -> str:
    """Return claimable|active|expired without automatically retrying work."""
    status = str(task.get("status") or "").lower()
    if status != "in_progress":
        return "claimable"

    current = now or datetime.now(timezone.utc)
    deadline = _parse_dt(task.get("a2a_lease_expires_at"))
    if deadline:
        return "active" if deadline > current else "expired"

    # Legacy in-progress records created before leases existed are allowed to
    # finish only inside their original timeout window. Once that window is
    # gone, block them. Never infer "retry" from a fresh heartbeat alone.
    started = _parse_dt(task.get("a2a_execution_started_at") or task.get("started_at"))
    if started and (current - started).total_seconds() > max(1, int(timeout_seconds)) + A2A_LEASE_GRACE_SECONDS:
        return "expired"
    return "active"


def _acquire_execution_lease(database: Any, task_id: str, agent_id: str, timeout_seconds: int) -> dict[str, Any]:
    """Atomically acquire the only permitted execution attempt for this task."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    deadline_iso = (now + timedelta(seconds=max(1, int(timeout_seconds)) + A2A_LEASE_GRACE_SECONDS)).isoformat()
    result = database[coordination_live.OPS_TASKS_COL].update_one(
        {
            "task_id": task_id,
            "status": "in_progress",
            "$or": [
                {"a2a_lease_expires_at": {"$exists": False}},
                {"a2a_lease_expires_at": None},
            ],
        },
        {
            "$set": {
                "a2a_execution_started_at": now_iso,
                "a2a_lease_expires_at": deadline_iso,
                "a2a_lease_state": "active",
                "a2a_target_agent": agent_id,
                "updated_at": now_iso,
            },
            "$inc": {"a2a_execution_attempt": 1},
        },
    )
    if not getattr(result, "modified_count", 0):
        return {"ok": False, "reason": "lease_not_acquired"}
    return {"ok": True, "started_at": now_iso, "expires_at": deadline_iso}


def _finish_execution_lease(database: Any, task_id: str, state: str, error: str = "") -> None:
    finished = datetime.now(timezone.utc).isoformat()
    patch: dict[str, Any] = {
        "a2a_lease_state": state,
        "a2a_lease_finished_at": finished,
        "updated_at": finished,
    }
    if error:
        patch["a2a_lease_error"] = error[:1000]
    database[coordination_live.OPS_TASKS_COL].update_one({"task_id": task_id}, {"$set": patch})


def _invoke_agent_bounded(agent_id: str, message: str, timeout_seconds: int) -> dict[str, Any]:
    from raphiia_openai.agents.pool_agent_runners import invoke_agent

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"a2a-{agent_id.lower()}")
    future = pool.submit(invoke_agent, agent_id, message, dry_run=False)
    try:
        result = future.result(timeout=max(1, int(timeout_seconds)))
        return result if isinstance(result, dict) else {"ok": False, "agent_id": agent_id, "error": "runner_result_not_dict"}
    except FutureTimeout:
        future.cancel()
        return {
            "ok": False,
            "agent_id": agent_id,
            "error": "agent_execution_timeout",
            "timeout_seconds": max(1, int(timeout_seconds)),
        }
    except Exception as exc:
        return {"ok": False, "agent_id": agent_id, "error": str(exc)}
    finally:
        # Never let a stuck runner hold the AG-25 daemon. A timed-out thread may
        # finish later, but its durable task is blocked and cannot auto-retry.
        pool.shutdown(wait=False, cancel_futures=True)


def controller_tick(
    limit: int = 4,
    dry_run: bool = False,
    db: Any | None = None,
    agent_timeout_seconds: int = DEFAULT_AGENT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
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
        plan = {
            "task_id": task_id,
            "agent_id": agent_id,
            "message_preview": message[:300],
            "transport": "a2a",
            "timeout_seconds": max(1, int(agent_timeout_seconds)),
        }
        planned.append(plan)
        if dry_run:
            continue

        try:
            current = database[coordination_live.OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or task
            current_status = str(current.get("status") or "").lower()
            lease_state = _execution_lease_state(current, max(1, int(agent_timeout_seconds)))

            if current_status == "in_progress" and lease_state == "active":
                executed.append({
                    **plan,
                    "ok": True,
                    "status": "leased",
                    "skipped": True,
                    "reason": "a2a_execution_already_active",
                })
                continue

            if lease_state == "expired":
                evidence = {
                    "status": "FAIL",
                    "transport": "a2a",
                    "controller": "AG-25",
                    "target_agent": agent_id,
                    "timeout": True,
                    "result": {"ok": False, "error": "a2a_execution_lease_expired"},
                }
                coordination_live.update_ops_task_state(
                    task_id,
                    "blocked",
                    actor="ralfia",
                    evidence=evidence,
                    force_handoff=True,
                )
                _finish_execution_lease(database, task_id, "expired", "a2a_execution_lease_expired")
                executed.append({
                    **plan,
                    "ok": True,
                    "task_ok": False,
                    "status": "blocked",
                    "remediated": True,
                    "error": "a2a_execution_lease_expired",
                })
                continue

            if current_status == "proposed":
                coordination_live.update_ops_task_state(task_id, "accepted", actor="ralfia", force_handoff=True)
            coordination_live.update_ops_task_state(task_id, "in_progress", actor="ralfia", force_handoff=True)
            lease = _acquire_execution_lease(database, task_id, agent_id, max(1, int(agent_timeout_seconds)))
            if not lease.get("ok"):
                executed.append({
                    **plan,
                    "ok": True,
                    "status": "leased",
                    "skipped": True,
                    "reason": lease.get("reason") or "lease_not_acquired",
                })
                continue
            coordination_live.heartbeat_ops_task(task_id, "ralfia", next_action=f"A2A execute {agent_id}", blocker=None)
        except Exception as exc:
            executed.append({**plan, "ok": False, "error": f"claim_failed:{exc}"})
            continue

        result = _invoke_agent_bounded(agent_id, message, max(1, int(agent_timeout_seconds)))
        ok = bool(result.get("ok"))
        timed_out = result.get("error") == "agent_execution_timeout"
        evidence = {
            "status": "PASS" if ok else "FAIL",
            "transport": "a2a",
            "controller": "AG-25",
            "target_agent": agent_id,
            "timeout": timed_out,
            "result": _clip_result(result),
        }
        target_status = "completed" if ok else "blocked"
        try:
            coordination_live.update_ops_task_state(task_id, target_status, actor="ralfia", evidence=evidence, force_handoff=True)
            _finish_execution_lease(database, task_id, "completed" if ok else "failed", str(result.get("error") or ""))
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
