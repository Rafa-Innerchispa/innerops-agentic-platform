"""Dry-run-first migration helpers for RACB messages and operational tasks."""

from __future__ import annotations

import hashlib
from typing import Any

from raphiia_openai import mongo_store, racb_protocol
from raphiia_openai.settings import COL_AGENT_MESSAGES

OPS_TASKS_COL = "ralfia_ops_tasks"


def _legacy_message_id(doc: dict[str, Any]) -> str:
    seed = "|".join(
        str(doc.get(key) or "")
        for key in ("_id", "created_at", "ts", "source_file", "title", "target_agent")
    )
    return f"msg_legacy_{hashlib.sha256(seed.encode()).hexdigest()[:16]}"


def plan_message_migration(doc: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    message_id = str(doc.get("message_id") or "").strip() or _legacy_message_id(doc)
    if not doc.get("message_id"):
        patch["message_id"] = message_id
    if not doc.get("from_agent"):
        patch["from_agent"] = str(doc.get("agent") or doc.get("from") or "SYSTEM").strip().upper()
    if not doc.get("target_agent") and doc.get("to_agent"):
        patch["target_agent"] = str(doc["to_agent"]).strip().lower()
    if doc.get("status") == "delivered":
        patch["status"] = "open"
    if not doc.get("type"):
        patch["type"] = "message"
    if not doc.get("correlation_id"):
        patch["correlation_id"] = message_id
    for key, default in (
        ("payload", {}),
        ("reply_to", None),
        ("idempotency_key", None),
        ("acknowledged_at", None),
        ("acknowledged_by", None),
    ):
        if key not in doc:
            patch[key] = default
    if int(doc.get("schema_version") or 0) < 3:
        patch["schema_version"] = 3
    return {
        "needs_migration": bool(patch),
        "identity": {"message_id": message_id, "mongo_id": str(doc.get("_id") or "")},
        "patch": patch,
    }


def plan_task_migration(doc: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    current_raw = str(doc.get("status") or "pending").strip().lower()
    normalized = racb_protocol.normalize_status(current_raw)
    if current_raw != normalized:
        patch["status"] = normalized
    if not doc.get("correlation_id"):
        patch["correlation_id"] = str(doc.get("task_id") or "legacy-task")
    if not doc.get("protocol_version"):
        patch["protocol_version"] = racb_protocol.PROTOCOL_VERSION
    if "revision" not in doc:
        patch["revision"] = 1
    if "state_history" not in doc:
        patch["state_history"] = []
    if "owner" not in doc:
        patch["owner"] = doc.get("assignee") if normalized in {"accepted", "in_progress", "blocked"} else None
    return {
        "needs_migration": bool(patch),
        "identity": {"task_id": doc.get("task_id"), "mongo_id": str(doc.get("_id") or "")},
        "patch": patch,
    }


def _apply_plan(collection, doc: dict[str, Any], plan: dict[str, Any]) -> bool:
    if not plan["needs_migration"]:
        return False
    if doc.get("_id") is not None:
        query = {"_id": doc["_id"]}
    elif doc.get("message_id"):
        query = {"message_id": doc["message_id"]}
    else:
        query = {"task_id": doc.get("task_id")}
    result = collection.update_one(query, {"$set": plan["patch"]})
    return result.modified_count == 1


def migrate_racb_records(*, dry_run: bool = True, limit: int = 500) -> dict[str, Any]:
    """Audit or migrate legacy records. Defaults to a non-writing dry run."""
    db = mongo_store.get_db()
    bounded_limit = max(1, min(int(limit), 5000))
    message_docs = list(db[COL_AGENT_MESSAGES].find({}).sort("created_at", -1).limit(bounded_limit))
    task_docs = list(db[OPS_TASKS_COL].find({}).sort("created_at", -1).limit(bounded_limit))
    message_plans = [(doc, plan_message_migration(doc)) for doc in message_docs]
    task_plans = [(doc, plan_task_migration(doc)) for doc in task_docs]

    changed_messages = 0
    changed_tasks = 0
    if not dry_run:
        for doc, plan in message_plans:
            changed_messages += int(_apply_plan(db[COL_AGENT_MESSAGES], doc, plan))
        for doc, plan in task_plans:
            changed_tasks += int(_apply_plan(db[OPS_TASKS_COL], doc, plan))

    pending_messages = [plan for _, plan in message_plans if plan["needs_migration"]]
    pending_tasks = [plan for _, plan in task_plans if plan["needs_migration"]]
    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "limit": bounded_limit,
        "scanned": {"messages": len(message_docs), "tasks": len(task_docs)},
        "would_migrate": {"messages": len(pending_messages), "tasks": len(pending_tasks)},
        "migrated": {"messages": changed_messages, "tasks": changed_tasks},
        "samples": {
            "messages": pending_messages[:5],
            "tasks": pending_tasks[:5],
        },
        "warning": None if dry_run else "Migration applied. Review coordination revision and audit before deployment.",
    }
