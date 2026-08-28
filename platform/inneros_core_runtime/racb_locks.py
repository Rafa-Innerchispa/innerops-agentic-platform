"""Lease-based resource locks for the RalfIA Agent Coordination Bus."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store

LOCKS_COL = "ralfia_coordination_locks"
CONFLICTS_COL = "ralfia_coordination_conflicts"
LOCK_ACTIONS = frozenset({"acquire", "renew", "release", "inspect", "list"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_active(lock: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    if not lock or lock.get("status") != "active":
        return False
    expiry = _parse(lock.get("expires_at"))
    return bool(expiry and expiry > (now or _now()))


def evaluate_lock_action(
    *,
    action: str,
    resource_id: str,
    agent: str,
    task_id: str | None,
    current: dict[str, Any] | None,
    ttl_seconds: int = 1800,
    force: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    action_n = (action or "").strip().lower()
    resource_n = (resource_id or "").strip()
    agent_n = (agent or "").strip().lower()
    task_n = (task_id or "").strip() or None
    if action_n not in LOCK_ACTIONS:
        return {"ok": False, "error": "invalid_action", "available": sorted(LOCK_ACTIONS)}
    if action_n != "list" and not resource_n:
        return {"ok": False, "error": "resource_id_required"}
    if action_n not in {"inspect", "list"} and not agent_n:
        return {"ok": False, "error": "agent_required"}

    now_dt = now or _now()
    ttl = max(30, min(int(ttl_seconds), 86400))
    active = is_active(current, now=now_dt)
    owner = (current or {}).get("owner")
    current_task = (current or {}).get("task_id")
    revision = int((current or {}).get("revision") or 0)

    if action_n == "inspect":
        return {"ok": True, "action": action_n, "active": active, "lock": current}

    if action_n in {"acquire", "renew"}:
        same_lease = active and owner == agent_n and current_task == task_n
        if active and not same_lease and not force:
            return {
                "ok": False,
                "error": "lock_conflict",
                "resource_id": resource_n,
                "owner": owner,
                "task_id": current_task,
                "expires_at": (current or {}).get("expires_at"),
            }
        if action_n == "renew" and not active and not force:
            return {"ok": False, "error": "lock_not_active", "resource_id": resource_n}

        expires_at = now_dt + timedelta(seconds=ttl)
        patch = {
            "resource_id": resource_n,
            "owner": agent_n,
            "task_id": task_n,
            "status": "active",
            "acquired_at": (current or {}).get("acquired_at") if same_lease else _iso(now_dt),
            "renewed_at": _iso(now_dt),
            "expires_at": _iso(expires_at),
            "revision": revision + 1,
            "updated_at": _iso(now_dt),
        }
        if force and active and not same_lease:
            patch.update({"previous_owner": owner, "previous_task_id": current_task, "forced_handoff": True})
        return {
            "ok": True,
            "action": "renew" if same_lease else "acquire",
            "idempotent_owner": same_lease,
            "patch": patch,
        }

    if action_n == "release":
        if not current:
            return {"ok": True, "action": "release", "idempotent": True, "released": False}
        if active and (owner != agent_n or (current_task and current_task != task_n)) and not force:
            return {"ok": False, "error": "lock_owner_mismatch", "owner": owner, "task_id": current_task}
        return {
            "ok": True,
            "action": "release",
            "idempotent": current.get("status") == "released",
            "patch": {
                "status": "released",
                "released_at": _iso(now_dt),
                "released_by": agent_n,
                "revision": revision + 1,
                "updated_at": _iso(now_dt),
            },
        }

    return {"ok": False, "error": "unsupported_action"}


def manage_coordination_lock(
    action: str,
    resource_id: str = "",
    agent: str = "",
    task_id: str | None = None,
    ttl_seconds: int = 1800,
    force: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Manage a lock lease; conflicts are recorded for later auditing."""
    db = mongo_store.get_db()
    action_n = (action or "").strip().lower()
    if action_n == "list":
        rows = list(
            db[LOCKS_COL]
            .find({"status": "active"}, {"_id": 0})
            .sort("updated_at", -1)
            .limit(max(1, min(int(limit), 200)))
        )
        return {"ok": True, "action": "list", "count": len(rows), "locks": rows}

    current = db[LOCKS_COL].find_one({"resource_id": resource_id}, {"_id": 0})
    decision = evaluate_lock_action(
        action=action_n,
        resource_id=resource_id,
        agent=agent,
        task_id=task_id,
        current=current,
        ttl_seconds=ttl_seconds,
        force=force,
    )
    if not decision.get("ok"):
        if decision.get("error") in {"lock_conflict", "lock_owner_mismatch"}:
            db[CONFLICTS_COL].insert_one(
                {
                    **decision,
                    "requested_by": (agent or "").strip().lower(),
                    "requested_task_id": task_id,
                    "created_at": _iso(_now()),
                }
            )
        return decision
    if action_n == "inspect" or decision.get("idempotent") and not decision.get("patch"):
        return decision

    revision = int((current or {}).get("revision") or 0)
    query: dict[str, Any] = {"resource_id": resource_id}
    if current:
        query["revision"] = revision
    update = {
        "$set": decision["patch"],
        "$push": {
            "history": {
                "action": decision["action"],
                "agent": (agent or "").strip().lower(),
                "task_id": task_id,
                "at": _iso(_now()),
                "revision": decision["patch"]["revision"],
            }
        },
    }
    result = db[LOCKS_COL].update_one(query, update, upsert=not bool(current))
    if result.modified_count != 1 and result.upserted_id is None:
        return {"ok": False, "error": "concurrent_lock_update", "resource_id": resource_id}
    return {
        "ok": True,
        "action": decision["action"],
        "resource_id": resource_id,
        "lock": decision["patch"],
        "idempotent_owner": decision.get("idempotent_owner", False),
    }
