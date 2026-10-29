"""Durable ops task requirement amendments (MESSAGE_DELIVERED ≠ REQUIREMENTS_APPLIED).

Each amendment is keyed by task_id + message_id + idempotency_key and moves through
pending → accepted|denied → applied → verified. Scope changes only via authorized CAS
on requirements_version; inbox ACK alone never applies requirements.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store, ralfia_time

COL_EVENTS = "ops_task_requirement_events"
TERMINAL_TASK = frozenset({"completed", "done", "failed", "cancelled", "canceled", "superseded", "archived"})
BLOCKING_LIFECYCLE = frozenset({"pending", "accepted", "applied"})


def _now() -> str:
    return ralfia_time.now_utc_iso()


def _event_id(task_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{task_id}|{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"req_{digest}"


def _task_requirements_version(task: dict[str, Any]) -> int:
    try:
        return int(task.get("requirements_version") or task.get("revision") or 0)
    except (TypeError, ValueError):
        return 0


def register_amendment(
    task_id: str,
    *,
    message_id: str,
    reply_to: str | None = None,
    correlation_id: str | None = None,
    idempotency_key: str,
    delta: dict[str, Any],
    source: str = "inbox",
    auto_accept: bool | None = None,
) -> dict[str, Any]:
    """Record a requirements change proposal; idempotent on idempotency_key."""
    tid = (task_id or "").strip()
    ikey = (idempotency_key or "").strip()
    if not tid or not ikey:
        return {"ok": False, "error": "task_id_and_idempotency_key_required"}
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": tid}

    eid = _event_id(tid, ikey)
    existing = db[COL_EVENTS].find_one({"event_id": eid}, {"_id": 0})
    if existing:
        return {"ok": True, "duplicate": True, "event_id": eid, "lifecycle": existing.get("lifecycle")}

    if auto_accept is None:
        auto_accept = os.getenv("INNEROS_OPS_AUTO_ACCEPT_AMENDMENTS", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    lifecycle = "accepted" if auto_accept else "pending"
    doc: dict[str, Any] = {
        "event_id": eid,
        "task_id": tid,
        "message_id": (message_id or "").strip(),
        "reply_to": (reply_to or "").strip() or None,
        "correlation_id": (correlation_id or "").strip() or None,
        "idempotency_key": ikey,
        "lifecycle": lifecycle,
        "source": source,
        "delta": dict(delta or {}),
        "requirements_version_at_register": _task_requirements_version(task),
        "created_at": _now(),
        "updated_at": _now(),
    }
    if lifecycle == "accepted":
        doc["accepted_at"] = doc["created_at"]
        doc["accepted_by"] = "auto_accept_policy"
    db[COL_EVENTS].insert_one(doc)
    return {"ok": True, "event_id": eid, "lifecycle": lifecycle, "task_id": tid}


def accept_amendment(
    event_id: str,
    *,
    actor: str = "owner",
    expected_requirements_version: int | None = None,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    ev = db[COL_EVENTS].find_one({"event_id": event_id}, {"_id": 0})
    if not ev:
        return {"ok": False, "error": "amendment_not_found", "event_id": event_id}
    if ev.get("lifecycle") != "pending":
        return {"ok": False, "error": "not_pending", "lifecycle": ev.get("lifecycle")}
    tid = str(ev.get("task_id") or "")
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0, "requirements_version": 1, "revision": 1})
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": tid}
    cur = _task_requirements_version(task)
    if expected_requirements_version is not None and cur != expected_requirements_version:
        return {
            "ok": False,
            "error": "requirements_version_mismatch",
            "expected": expected_requirements_version,
            "actual": cur,
        }
    now = _now()
    updated = db[COL_EVENTS].find_one_and_update(
        {"event_id": event_id, "lifecycle": "pending"},
        {"$set": {"lifecycle": "accepted", "accepted_at": now, "accepted_by": actor, "updated_at": now}},
        return_document=True,
    )
    if not updated:
        return {"ok": False, "error": "accept_conflict", "event_id": event_id}
    return {"ok": True, "event_id": event_id, "lifecycle": "accepted", "task_id": tid}


def deny_amendment(event_id: str, *, actor: str = "owner", reason: str = "") -> dict[str, Any]:
    db = mongo_store.get_db()
    now = _now()
    updated = db[COL_EVENTS].find_one_and_update(
        {"event_id": event_id, "lifecycle": "pending"},
        {
            "$set": {
                "lifecycle": "denied",
                "denied_at": now,
                "denied_by": actor,
                "deny_reason": (reason or "")[:500],
                "updated_at": now,
            }
        },
        return_document=True,
    )
    if not updated:
        return {"ok": False, "error": "deny_conflict", "event_id": event_id}
    return {"ok": True, "event_id": event_id, "lifecycle": "denied"}


def _merge_delta(task: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key in ("objective", "title", "preferred_model", "execution_policy", "task_class"):
        if key in delta and delta[key] is not None:
            patch[key] = delta[key]
    if isinstance(delta.get("checklist"), list):
        patch["checklist"] = delta["checklist"]
    if isinstance(delta.get("payload"), dict):
        base = dict(task.get("payload") or {})
        base.update(delta["payload"])
        patch["payload"] = base
    if delta.get("append_objective"):
        prev = str(task.get("objective") or "")
        patch["objective"] = (prev + "\n" + str(delta["append_objective"]))[:8000]
    return patch


def apply_amendment(event_id: str, *, actor: str = "executor") -> dict[str, Any]:
    db = mongo_store.get_db()
    ev = db[COL_EVENTS].find_one({"event_id": event_id}, {"_id": 0})
    if not ev or ev.get("lifecycle") != "accepted":
        return {"ok": False, "error": "amendment_not_accepted", "event_id": event_id}
    tid = str(ev.get("task_id") or "")
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": tid}
    status = str(task.get("status") or "").lower()
    if status in TERMINAL_TASK:
        cont = create_continuation_for_amendment(ev, parent=task)
        return {"ok": True, "continuation": cont, "event_id": event_id, "parent_terminal": True}

    base_ver = _task_requirements_version(task)
    at_register = int(ev.get("requirements_version_at_register") or base_ver)
    if base_ver != at_register:
        return {
            "ok": False,
            "error": "stale_amendment_base_version",
            "at_register": at_register,
            "current": base_ver,
        }
    patch = _merge_delta(task, dict(ev.get("delta") or {}))
    new_ver = base_ver + 1
    now = _now()
    patch.update(
        {
            "requirements_version": new_ver,
            "last_amendment_event_id": event_id,
            "last_amendment_applied_at": now,
            "updated_at": now,
        }
    )
    applied_task = db[OPS_TASKS_COL].find_one_and_update(
        {"task_id": tid, "requirements_version": base_ver},
        {"$set": patch, "$inc": {"revision": 1}},
        return_document=True,
    )
    if not applied_task:
        return {"ok": False, "error": "apply_cas_conflict", "task_id": tid}
    db[COL_EVENTS].update_one(
        {"event_id": event_id, "lifecycle": "accepted"},
        {"$set": {"lifecycle": "applied", "applied_at": now, "applied_by": actor, "updated_at": now}},
    )
    return {"ok": True, "event_id": event_id, "task_id": tid, "requirements_version": new_ver}


def verify_amendment(event_id: str, *, actor: str = "verifier") -> dict[str, Any]:
    db = mongo_store.get_db()
    now = _now()
    updated = db[COL_EVENTS].find_one_and_update(
        {"event_id": event_id, "lifecycle": "applied"},
        {"$set": {"lifecycle": "verified", "verified_at": now, "verified_by": actor, "updated_at": now}},
        return_document=True,
    )
    if not updated:
        return {"ok": False, "error": "verify_conflict", "event_id": event_id}
    return {"ok": True, "event_id": event_id, "lifecycle": "verified"}


def pending_amendments(task_id: str) -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    rows = list(
        db[COL_EVENTS].find(
            {"task_id": task_id.strip(), "lifecycle": {"$in": sorted(BLOCKING_LIFECYCLE)}},
            {"_id": 0},
        ).sort("created_at", 1)
    )
    return rows


def completion_blocked_by_amendments(task_id: str) -> dict[str, Any]:
    pending = pending_amendments(task_id)
    if not pending:
        return {"blocked": False, "pending": []}
    return {
        "blocked": True,
        "error": "pending_requirements_amendments",
        "pending": [{"event_id": p.get("event_id"), "lifecycle": p.get("lifecycle")} for p in pending],
    }


def checkpoint_pending_revision(task_id: str) -> dict[str, Any]:
    """Load accepted/applied-but-unverified deltas for agent resume on same claim."""
    db = mongo_store.get_db()
    rows = list(
        db[COL_EVENTS].find(
            {"task_id": task_id.strip(), "lifecycle": {"$in": ["accepted", "applied"]}},
            {"_id": 0},
        ).sort("created_at", 1)
    )
    return {"task_id": task_id, "pending_events": rows, "count": len(rows)}


def create_continuation_for_amendment(event: dict[str, Any], *, parent: dict[str, Any]) -> dict[str, Any]:
    """One dependent continuation when parent is terminal but amendment still has work."""
    from inneros_core_runtime import coordination_live as cl

    tid = str(parent.get("task_id") or "")
    ikey = f"continuation|{event.get('event_id')}|{tid}"
    existing = mongo_store.get_db()[OPS_TASKS_COL].find_one({"idempotency_key": ikey}, {"task_id": 1})
    if existing:
        return {"ok": True, "duplicate": True, "task_id": existing.get("task_id")}
    suffix = secrets.token_hex(4)
    delta = dict(event.get("delta") or {})
    title = str(delta.get("title") or parent.get("title") or f"Continuation of {tid}")[:200]
    objective = str(delta.get("objective") or delta.get("append_objective") or parent.get("objective") or "")[:8000]
    return cl.create_ops_task(
        assignee=str(parent.get("assignee") or parent.get("preferred_provider") or "cursor"),
        title=f"[continuation] {title}",
        objective=objective,
        correlation_id=str(parent.get("correlation_id") or tid),
        repo=str(parent.get("repo") or "").strip() or None,
        task_class=str(parent.get("task_class") or "coding"),
        execution_lane=str(parent.get("execution_lane") or ""),
        preferred_provider=str(parent.get("preferred_provider") or parent.get("assignee") or ""),
        payload={
            **(dict(parent.get("payload") or {})),
            "continues_from_task_id": tid,
            "continues_from_event_id": event.get("event_id"),
            "requirements_amendment_continuation": True,
        },
        idempotency_key=ikey,
        from_agent=str(parent.get("from_agent") or "inneros"),
    )


def ingest_message_as_amendment(message: dict[str, Any]) -> dict[str, Any]:
    """Build amendment from a delivered agent message (no new ops task)."""
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    tid = str(payload.get("task_id") or payload.get("amends_task_id") or message.get("task_id") or "").strip()
    if not tid and message.get("reply_to"):
        db = mongo_store.get_db()
        from raphiia_openai.settings import COL_AGENT_MESSAGES

        parent = db[COL_AGENT_MESSAGES].find_one({"message_id": message.get("reply_to")}, {"task_id": 1, "payload": 1})
        if parent:
            tid = str(parent.get("task_id") or (parent.get("payload") or {}).get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "amendment_task_id_unresolved"}
    body = str(message.get("body") or "")
    delta: dict[str, Any] = dict(payload.get("requirements_delta") or {})
    if not delta and body.strip():
        delta["append_objective"] = body.strip()[:8000]
    if payload.get("preferred_model"):
        delta["preferred_model"] = payload["preferred_model"]
    ikey = str(
        payload.get("idempotency_key")
        or message.get("idempotency_key")
        or f"msg:{message.get('message_id') or _now()}"
    ).strip()
    return register_amendment(
        tid,
        message_id=str(message.get("message_id") or ""),
        reply_to=str(message.get("reply_to") or "") or None,
        correlation_id=str(message.get("correlation_id") or "") or None,
        idempotency_key=ikey,
        delta=delta,
        source="agent_message",
    )
