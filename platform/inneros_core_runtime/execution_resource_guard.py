"""Durable resource admission for InnerOS execution, independent of workflow retries."""
from __future__ import annotations

import contextvars
import functools
import inspect
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from typing import get_type_hints

from raphiia_openai import mongo_store

TASKS = "ralfia_ops_tasks"
STATE = "ralfia_coordination_state"
MAX_EXECUTIONS = 3
MAX_MODEL_CALLS = 12
MAX_TASK_SECONDS = 1800
LOCAL_SLOTS = 4
_context = contextvars.ContextVar("inneros_execution_resource", default=None)
CONTROL_KEY = "execution_resource_guard_control"


def _now():
    return datetime.now(timezone.utc)


def denied(reason: str) -> dict[str, Any]:
    return {"ok": False, "blocked": True, "error": reason,
            "resource_guard": True, "requires_bounded_executor": False}


def _reserve_provider_allowance(db, provider: str) -> bool:
    if provider not in {"cursor", "codex", "antigravity", "gemini"}:
        return True
    from inneros_core_runtime.external_repair_agent import _credit_config
    cfg = _credit_config()
    now = _now()
    for period, stamp in (("daily", now.strftime("%Y-%m-%d")), ("monthly", now.strftime("%Y-%m"))):
        limit = int((cfg.get(period + "_hard_limit") or {}).get(provider, 0))
        if limit <= 0:
            return False
        key = f"execution_resource_guard:{provider}:{period}:{stamp}"
        db[STATE].update_one({"_id": key}, {"$setOnInsert": {"key": key, "state": {"reserved": 0}}}, upsert=True)
        if not db[STATE].find_one_and_update(
            {"_id": key, "state.reserved": {"$lt": limit}},
            {"$inc": {"state.reserved": 1}}, return_document=True,
        ):
            return False
    return True


def reserve(task_id: str, provider: str) -> dict[str, Any]:
    """Atomically spend one attempt before executing; never reset on restart."""
    db = mongo_store.get_db()
    control = db[STATE].find_one({"key": CONTROL_KEY}) or {}
    if (control.get("state") or {}).get("block_new_work"):
        return denied("resource_global_circuit_open")
    task = db[TASKS].find_one({"task_id": task_id}) or {}
    payload = task.get("payload") or {}
    if task.get("status") not in {"claimed", "in_progress", "running", "proposed"}:
        return denied("resource_task_not_executable")
    if task.get("superseded_by") or task.get("execution_stop"):
        return denied("resource_task_stopped_or_superseded")
    if task.get("do_not_auto_dispatch") or payload.get("do_not_auto_dispatch"):
        return denied("resource_manual_dispatch_only")
    if task.get("execution_paused_for_deploy") or payload.get("execution_paused_for_deploy"):
        return denied("resource_execution_paused")
    if any("interactive" in str(s.get("execution_lane") or "") for s in (task, payload)):
        return denied("resource_interactive_lane")
    if (task.get("headless_last_result") or {}).get("completion_submitted"):
        return denied("resource_success_already_submitted")
    if provider in {"cursor", "codex", "antigravity", "gemini"}:
        if not task.get("owner_authorized_at") or not task.get("claim_token"):
            return denied("resource_external_authorization_missing")
    token = secrets.token_hex(16)
    ledger = task.get("resource_guard") or {}
    if ledger.get("last_outcome") == "success":
        return denied("resource_success_already_submitted")
    # Match lifecycle and stop fields again at reservation to reject racing cancels.
    query = {
        "task_id": task_id, "status": task["status"],
        "superseded_by": {"$in": [None, ""]}, "execution_stop": {"$exists": False},
        "do_not_auto_dispatch": {"$ne": True}, "payload.do_not_auto_dispatch": {"$ne": True},
        "resource_guard.active_token": {"$exists": False},
        "resource_guard.last_outcome": {"$ne": "success"},
        "resource_guard.stop_reason": {"$exists": False},
        "$and": [
            {"$or": [{"resource_guard.attempts": {"$exists": False}},
                     {"resource_guard.attempts": {"$lt": MAX_EXECUTIONS}}]},
            {"$or": [{"resource_guard.elapsed_seconds": {"$exists": False}},
                     {"resource_guard.elapsed_seconds": {"$lt": MAX_TASK_SECONDS}}]},
        ],
    }
    row = db[TASKS].find_one_and_update(query, {
        "$set": {"resource_guard.active_token": token, "resource_guard.provider": provider,
                 "resource_guard.started_at": _now().isoformat()},
        "$inc": {"resource_guard.attempts": 1},
    }, return_document=True)
    if not row:
        return denied("resource_budget_exhausted_or_execution_active")
    reservation = {"ok": True, "task_id": task_id, "token": token, "provider": provider}
    try:
        if not _reserve_provider_allowance(db, provider):
            finish(reservation, elapsed=0, success=False)
            return denied("resource_provider_allowance_exhausted")
    except Exception:
        finish(reservation, elapsed=0, success=False)
        raise
    return reservation


def finish(reservation, *, elapsed: float, success: bool) -> None:
    mongo_store.get_db()[TASKS].update_one(
        {"task_id": reservation["task_id"], "resource_guard.active_token": reservation["token"]},
        {"$unset": {"resource_guard.active_token": ""},
         "$inc": {"resource_guard.elapsed_seconds": elapsed},
         "$set": {"resource_guard.finished_at": _now().isoformat(),
                  "resource_guard.last_outcome": "success" if success else "failed"}},
    )


def guard_execution(provider: str, argument: str, *, provider_argument: str = ""):
    """Wrap existing executors; nested calls share their parent's durable budget."""
    def decorate(fn):
        signature = inspect.signature(fn)

        def admit(args, kwargs):
            values = signature.bind(*args, **kwargs).arguments
            value = values.get(argument)
            tid = str(value.get("task_id") or "") if isinstance(value, dict) else str(value or "")
            current = _context.get()
            if current and current["task_id"] == tid:
                selected = str(values.get(provider_argument) or provider)
                if selected in {"cursor", "codex", "antigravity", "gemini"} and selected != current["provider"]:
                    return denied("resource_paid_provider_switch_denied"), None
                return current, None
            try:
                reservation = reserve(tid, str(values.get(provider_argument) or provider))
            except Exception:
                return denied("resource_ledger_unavailable"), None
            return reservation, _context.set(reservation) if reservation.get("ok") else None

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def wrapper(*args, **kwargs):
                reservation, context_token = admit(args, kwargs)
                if not reservation.get("ok"):
                    return reservation
                if context_token is None:
                    return await fn(*args, **kwargs)
                start = time.monotonic(); success = False
                try:
                    result = await fn(*args, **kwargs)
                    success = isinstance(result, dict) and result.get("ok") is True
                    return result
                finally:
                    _context.reset(context_token)
                    finish(reservation, elapsed=time.monotonic() - start, success=success)
        else:
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                reservation, context_token = admit(args, kwargs)
                if not reservation.get("ok"):
                    return reservation
                if context_token is None:
                    return fn(*args, **kwargs)
                start = time.monotonic(); success = False
                try:
                    result = fn(*args, **kwargs)
                    success = isinstance(result, dict) and result.get("ok") is True
                    return result
                finally:
                    _context.reset(context_token)
                    finish(reservation, elapsed=time.monotonic() - start, success=success)
        wrapper.__annotations__ = get_type_hints(fn)
        return wrapper
    return decorate


def guard_local_inference(fn):
    """Four cluster-wide leases; task-bound requests also spend a model-call budget."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        token = secrets.token_hex(16)
        slot = None
        try:
            db = mongo_store.get_db()
            control = db[STATE].find_one({"key": CONTROL_KEY}) or {}
            if (control.get("state") or {}).get("block_new_work"):
                return denied("resource_global_circuit_open")
            current = _context.get()
            if current:
                row = db[TASKS].find_one_and_update({
                    "task_id": current["task_id"], "resource_guard.active_token": current["token"],
                    "status": {"$in": ["proposed", "claimed", "in_progress", "running"]},
                    "execution_stop": {"$exists": False},
                    "$or": [{"resource_guard.model_calls": {"$exists": False}},
                            {"resource_guard.model_calls": {"$lt": MAX_MODEL_CALLS}}],
                }, {"$inc": {"resource_guard.model_calls": 1}}, return_document=True)
                if not row:
                    return denied("resource_model_call_budget_exhausted_or_stopped")
            now = _now()
            for n in range(LOCAL_SLOTS):
                key = f"execution_resource_guard:local_inference:{n}"
                db[STATE].update_one({"_id": key}, {"$setOnInsert": {"key": key, "state": {}}}, upsert=True)
                row = db[STATE].find_one_and_update({"_id": key, "$or": [
                    {"state.token": {"$exists": False}}, {"state.lease_until": {"$lte": now.isoformat()}},
                ]}, {"$set": {"state.token": token, "state.started_at": now.isoformat(),
                              "state.lease_until": (now + timedelta(seconds=900)).isoformat()}}, return_document=True)
                if row:
                    slot = key
                    break
        except Exception:
            return denied("resource_inference_ledger_unavailable")
        if slot is None:
            return denied("resource_local_inference_capacity_full")
        try:
            return fn(*args, **kwargs)
        finally:
            db[STATE].update_one({"_id": slot, "state.token": token}, {"$unset": {"state.token": ""}})
    return wrapper
