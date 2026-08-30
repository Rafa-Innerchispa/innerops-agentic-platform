"""Durable A2A facade backed by the InnerOS coordination plane."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import coordination_live, mongo_store
from raphiia_openai.a2a_agent_registry import merged_agent_cards, normalize_agent_key

BRIDGE_VERSION = "a2a-inneros-1.0"
PROTOCOL_VERSION = "0.3.0-inneros"
TASK_COL = "inneros_a2a_tasks"

BASE_CARDS: dict[str, dict[str, Any]] = {
    "codex-repair": {
        "name": "Codex Repair",
        "description": "Infrastructure code repair through isolated worktrees, tests and MCP evidence.",
        "url": "inneros://a2a/codex-repair",
        "version": BRIDGE_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{"id": "codex-repair", "name": "Codex Repair", "description": "Safe infrastructure repair"}],
        "metadata": {"agent_id": "codex-repair", "assignee": "codex", "domain": "platform", "local_first": False},
    },
    "integration-guardian": {
        "name": "Integration Guardian",
        "description": "Read-only/approval-gated integration verification and regression evidence.",
        "url": "inneros://a2a/integration-guardian",
        "version": BRIDGE_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{"id": "integration-guardian", "name": "Integration Guardian", "description": "Evidence checks"}],
        "metadata": {"agent_id": "integration-guardian", "assignee": "ralfia", "domain": "ops", "local_first": True},
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cards() -> dict[str, dict[str, Any]]:
    return merged_agent_cards(BASE_CARDS, PROTOCOL_VERSION, BRIDGE_VERSION)


def _task_id(seed: str) -> str:
    return "a2a_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _assignee_for_card(card: dict[str, Any], fallback_agent_id: str) -> str:
    meta = card.get("metadata") or {}
    assignee = str(meta.get("assignee") or "").strip().lower()
    if assignee in coordination_live.ASSIGNEES:
        return assignee
    agent = normalize_agent_key(fallback_agent_id)
    if agent == "codex-repair":
        return "codex"
    if agent in {"cursor", "antigravity", "gemini"}:
        return agent
    return "ralfia"


def status() -> dict[str, Any]:
    cards = _cards()
    db_ok = True
    db_error = ""
    try:
        mongo_store.get_db()[TASK_COL].find_one({}, {"_id": 0})
    except Exception as exc:
        db_ok = False
        db_error = str(exc)[:300]
    return {
        "ok": db_ok,
        "status": {"state": "online" if db_ok else "degraded", "message": db_error or "A2A durable bridge online"},
        "bridge_version": BRIDGE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "transport": "inneros_coordination_live",
        "agent_count": len(cards),
        "capabilities": {"agent_cards": True, "durable_dispatch": True, "state_projection": True, "shell_access": False, "production_deploy": False},
    }


def agent_cards() -> dict[str, Any]:
    cards = _cards()
    return {"ok": True, "bridge_version": BRIDGE_VERSION, "protocol_version": PROTOCOL_VERSION, "count": len(cards), "cards": cards}


def dispatch(
    *,
    agent_id: str,
    title: str,
    body: str,
    correlation_id: str = "",
    context_id: str = "",
    priority: str = "p0",
    related_project: str | None = "inneros",
    dry_run: bool = False,
    protocol_task_id: str = "",
) -> dict[str, Any]:
    cards = _cards()
    canonical = normalize_agent_key(agent_id)
    card = cards.get(canonical)
    if not card:
        return {"ok": False, "error": "unknown_a2a_agent", "agent_id": agent_id, "normalized": canonical, "known": list(cards)[:20]}
    clean_title = (title or "").strip()
    clean_body = (body or "").strip()
    if not clean_title or not clean_body:
        return {"ok": False, "error": "title_and_body_required"}
    cid = (correlation_id or "").strip() or _task_id(f"{canonical}:{clean_title}:{clean_body}")
    a2a_id = (protocol_task_id or "").strip() or _task_id(f"{canonical}:{cid}:{clean_title}")
    assignee = _assignee_for_card(card, canonical)
    envelope = {
        "a2a_task_id": a2a_id,
        "agent_id": canonical,
        "assignee": assignee,
        "title": clean_title,
        "body": clean_body,
        "correlation_id": cid,
        "context_id": (context_id or "").strip() or None,
        "priority": (priority or "normal").lower(),
        "related_project": related_project,
        "card_url": card.get("url"),
        "bridge_version": BRIDGE_VERSION,
        "created_at": _now(),
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "task": envelope, "card": card, "executed": False}
    task = coordination_live.create_ops_task(
        assignee=assignee,
        title=clean_title,
        checklist=[clean_body],
        evidence_required=["RACB state transition evidence", "tests/probe output when applicable"],
        priority=priority,
        from_agent="A2A",
        correlation_id=cid,
        related_project=related_project,
    )
    doc = {**envelope, "ops_task_id": task.get("task_id"), "ops_created": task.get("created"), "updated_at": _now()}
    mongo_store.get_db()[TASK_COL].update_one({"a2a_task_id": a2a_id}, {"$set": doc, "$setOnInsert": {"first_seen_at": doc["created_at"]}}, upsert=True)
    return {"ok": bool(task.get("ok")), "dry_run": False, "task": doc, "ops_task": task, "card": card, "executed": bool(task.get("ok"))}


def task_status(a2a_task_id: str) -> dict[str, Any]:
    key = (a2a_task_id or "").strip()
    if not key:
        return {"ok": False, "error": "a2a_task_id_required"}
    doc = mongo_store.get_db()[TASK_COL].find_one({"a2a_task_id": key}, {"_id": 0})
    if not doc:
        return {"ok": False, "error": "a2a_task_not_found", "a2a_task_id": key}
    ops_task = None
    if doc.get("ops_task_id"):
        rows = coordination_live.list_ops_tasks(assignee=doc.get("assignee"), status=None, limit=200).get("tasks") or []
        ops_task = next((row for row in rows if row.get("task_id") == doc.get("ops_task_id")), None)
    return {"ok": True, "a2a_task_id": key, "task": doc, "ops_task": ops_task, "status": (ops_task or {}).get("status") or "submitted"}
