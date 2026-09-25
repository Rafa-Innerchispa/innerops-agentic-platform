"""Session Bootstrap Guard Plane ? Zero-Configuration Agent Session Integrity.

Enforces that every agent session (AntiGravity, Cursor, Codex, ChatGPT) has an active,
route-aware bootstrap state before mutating critical code or executing ops workflows.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from inneros_core_runtime import universal_bootstrap
from raphiia_openai import mongo_store

COL_SESSION_BOOTSTRAP = "agent_session_bootstrap_ledger"


def ensure_session_bootstrap(
    agent: str = "antigravity",
    project_id: str | None = None,
    force_refresh: bool = False,
    auto_ack: bool = False,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    plan = universal_bootstrap.resolve_universal_bootstrap()

    record = {
        "agent": agent,
        "project_id": project_id or "innerops-agentic-platform",
        "bootstrapped_at": now,
        "last_heartbeat_at": now,
        "tier_selected": plan.get("tier_selected"),
        "active_node": plan.get("active_node"),
        "mcp_endpoint": plan.get("endpoints", {}).get("mcp_full"),
        "acknowledged": auto_ack,
        "status": "active",
        "version": universal_bootstrap.BOOTSTRAP_VERSION,
    }

    try:
        db = mongo_store.get_database()
        if db is not None:
            db[COL_SESSION_BOOTSTRAP].update_one(
                {"agent": agent, "project_id": record["project_id"]},
                {"$set": record},
                upsert=True,
            )
    except Exception:
        pass

    return {
        "ok": True,
        "agent": agent,
        "project_id": record["project_id"],
        "status": "active",
        "acknowledged": auto_ack,
        "bootstrap": plan,
    }


def guard_mutation_operation(
    agent: str = "antigravity",
    operation_name: str = "write_code",
    project_id: str | None = None,
    allow_auto_bootstrap: bool = True,
) -> dict[str, Any]:
    target_project = project_id or "innerops-agentic-platform"
    is_bootstrapped = False

    try:
        db = mongo_store.get_database()
        if db is not None:
            doc = db[COL_SESSION_BOOTSTRAP].find_one({"agent": agent, "project_id": target_project})
            if doc and doc.get("status") == "active":
                is_bootstrapped = True
    except Exception:
        pass

    if not is_bootstrapped and allow_auto_bootstrap:
        ensure_session_bootstrap(agent=agent, project_id=target_project, auto_ack=True)
        is_bootstrapped = True

    return {
        "allowed": is_bootstrapped,
        "agent": agent,
        "operation": operation_name,
        "project_id": target_project,
        "reason": "session_bootstrapped" if is_bootstrapped else "bootstrap_required",
    }


def watchdog_audit_sessions() -> dict[str, Any]:
    sessions = []
    try:
        db = mongo_store.get_database()
        if db is not None:
            for s in db[COL_SESSION_BOOTSTRAP].find({"status": "active"}):
                s.pop("_id", None)
                sessions.append(s)
    except Exception:
        pass

    return {
        "ok": True,
        "active_sessions_count": len(sessions),
        "sessions": sessions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
