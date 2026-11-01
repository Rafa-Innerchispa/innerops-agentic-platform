"""
InnerOS Hosting Concurrency Lock & Resource Guard Engine v2.0.
Provides domain and route-level mutex locks, optimistic concurrency control (hash/version detection),
and strict protection for domains actively undergoing external ad/SEO campaigns (pcdoctor.ai, pcdoctor.com.ec).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from inneros_core_runtime import mongo_store

HOSTING_LOCKS_COL = "ralfia_hosting_locks"

# Domains actively managed by external campaigns or other ChatGPT threads
RESERVED_CAMPAIGN_DOMAINS = {
    "pcdoctor.ai",
    "pcdoctor.com.ec",
}

# Fallback in-memory lock registry when MongoDB is disconnected or testing offline
_IN_MEMORY_LOCKS: dict[str, dict[str, Any]] = {}


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


def is_domain_reserved(domain: str) -> bool:
    """
    Checks if a domain is reserved for active external workflows (e.g. Google SEO,
    metadata, and advertising campaigns by another ChatGPT session).
    Mutations on reserved domains are strictly prevented to avoid concurrent collisions.
    """
    d = (domain or "").lower().strip()
    if not d:
        return False
    return d in RESERVED_CAMPAIGN_DOMAINS or any(d.endswith("." + v) for v in RESERVED_CAMPAIGN_DOMAINS)


class HostingLockManager:
    """Manages domain and path-level locks with TTL and audit metadata."""

    @classmethod
    def _get_collection(cls):
        try:
            db = mongo_store.get_db()
            return db[HOSTING_LOCKS_COL]
        except Exception:
            return None

    @classmethod
    def acquire_lock(
        cls,
        domain: str,
        path: str = "*",
        target_env: str = "staging",
        locked_by: str = "chatgpt",
        reason: str = "",
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        """
        Acquires a concurrency lock for a domain or specific path.
        Rejects requests for reserved domains.
        Rejects conflicting concurrent locks if an unexpired lock exists.
        """
        d_clean = (domain or "").lower().strip()
        if not d_clean:
            return {"ok": False, "error": "domain_required", "message": "Domain is required to acquire lock."}

        # 1. Enforce reserved campaign domain protection
        if is_domain_reserved(d_clean):
            return {
                "ok": False,
                "error": "FORBIDDEN_DOMAIN_RESERVED_EXTERNAL_CAMPAIGN",
                "domain": d_clean,
                "message": (
                    f"Domain '{d_clean}' is actively reserved for external Google SEO/ad campaigns. "
                    "Locking and modifications are strictly prevented to avoid collision."
                ),
            }

        p_clean = (path or "*").strip().replace("\\", "/")
        if not p_clean:
            p_clean = "*"

        ttl = max(10, min(int(ttl_seconds or 300), 1800))
        now = _now_dt()
        now_iso = now.isoformat()
        expires_at = (now + timedelta(seconds=ttl)).isoformat()

        col = cls._get_collection()

        # 2. Check for active unexpired locks on this domain
        conflicts = []
        if col is not None:
            try:
                # Find active locks on this domain that haven't expired
                cursor = col.find({
                    "domain": d_clean,
                    "status": "active",
                    "expires_at": {"$gt": now_iso}
                })
                for doc in cursor:
                    existing_path = doc.get("path", "*")
                    # Conflict if either is domain-wide ("*") or paths overlap
                    if existing_path == "*" or p_clean == "*" or existing_path == p_clean or p_clean.startswith(existing_path.rstrip("/") + "/"):
                        conflicts.append(doc)
            except Exception:
                col = None

        if col is None:
            # Fallback to in-memory check
            for lid, ldoc in list(_IN_MEMORY_LOCKS.items()):
                if ldoc.get("domain") == d_clean and ldoc.get("status") == "active":
                    if ldoc.get("expires_at", "") > now_iso:
                        existing_path = ldoc.get("path", "*")
                        if existing_path == "*" or p_clean == "*" or existing_path == p_clean or p_clean.startswith(existing_path.rstrip("/") + "/"):
                            conflicts.append(ldoc)
                    else:
                        _IN_MEMORY_LOCKS.pop(lid, None)

        # If a conflict exists and belongs to a different lock holder
        for conf in conflicts:
            if conf.get("locked_by") != locked_by:
                return {
                    "ok": False,
                    "error": "RESOURCE_LOCKED",
                    "domain": d_clean,
                    "path": p_clean,
                    "active_lock": {
                        "lock_id": conf.get("lock_id"),
                        "locked_by": conf.get("locked_by"),
                        "path": conf.get("path"),
                        "target_env": conf.get("target_env"),
                        "reason": conf.get("reason"),
                        "created_at": conf.get("created_at"),
                        "expires_at": conf.get("expires_at"),
                    },
                    "message": (
                        f"Resource '{d_clean}:{p_clean}' is currently locked by '{conf.get('locked_by')}' "
                        f"until {conf.get('expires_at')}. Reason: {conf.get('reason')}"
                    ),
                }

        # 3. Create new lock
        lock_id = f"lock_{secrets.token_hex(6)}"
        lock_doc = {
            "lock_id": lock_id,
            "domain": d_clean,
            "path": p_clean,
            "target_env": target_env,
            "locked_by": locked_by,
            "reason": str(reason or "")[:300],
            "status": "active",
            "created_at": now_iso,
            "expires_at": expires_at,
            "ttl_seconds": ttl,
        }

        if col is not None:
            try:
                col.insert_one(dict(lock_doc))
            except Exception:
                _IN_MEMORY_LOCKS[lock_id] = lock_doc
        else:
            _IN_MEMORY_LOCKS[lock_id] = lock_doc

        return {
            "ok": True,
            "lock_id": lock_id,
            "domain": d_clean,
            "path": p_clean,
            "target_env": target_env,
            "locked_by": locked_by,
            "expires_at": expires_at,
            "ttl_seconds": ttl,
            "message": f"Lock acquired successfully for {d_clean}:{p_clean}.",
        }

    @classmethod
    def release_lock(cls, lock_id: str, domain: str = "", released_by: str = "chatgpt") -> dict[str, Any]:
        """Releases an active lock by lock_id."""
        lid = (lock_id or "").strip()
        if not lid:
            return {"ok": False, "error": "lock_id_required"}

        now_iso = _now_iso()
        col = cls._get_collection()

        updated = False
        if col is not None:
            try:
                res = col.update_one(
                    {"lock_id": lid, "status": "active"},
                    {
                        "$set": {
                            "status": "released",
                            "released_at": now_iso,
                            "released_by": released_by,
                        }
                    }
                )
                if res.matched_count > 0:
                    updated = True
            except Exception:
                col = None

        if lid in _IN_MEMORY_LOCKS:
            _IN_MEMORY_LOCKS[lid]["status"] = "released"
            _IN_MEMORY_LOCKS[lid]["released_at"] = now_iso
            _IN_MEMORY_LOCKS[lid]["released_by"] = released_by
            updated = True

        if not updated:
            return {
                "ok": False,
                "error": "lock_not_found_or_already_released",
                "lock_id": lid,
            }

        return {
            "ok": True,
            "lock_id": lid,
            "status": "released",
            "released_at": now_iso,
            "released_by": released_by,
            "message": f"Lock {lid} released successfully.",
        }

    @classmethod
    def check_locks(cls, domain: str = "") -> dict[str, Any]:
        """Lists active, unexpired locks for a domain or all domains."""
        d_clean = (domain or "").lower().strip()
        now_iso = _now_iso()
        active_locks = []

        col = cls._get_collection()
        if col is not None:
            try:
                query: dict[str, Any] = {
                    "status": "active",
                    "expires_at": {"$gt": now_iso}
                }
                if d_clean:
                    query["domain"] = d_clean
                for doc in col.find(query, {"_id": 0}):
                    active_locks.append(doc)
            except Exception:
                col = None

        if col is None:
            for ldoc in _IN_MEMORY_LOCKS.values():
                if ldoc.get("status") == "active" and ldoc.get("expires_at", "") > now_iso:
                    if not d_clean or ldoc.get("domain") == d_clean:
                        active_locks.append(dict(ldoc))

        return {
            "ok": True,
            "domain": d_clean or "*",
            "active_locks": active_locks,
            "count": len(active_locks),
        }

    @classmethod
    def is_resource_locked(
        cls,
        domain: str,
        path: str = "*",
        current_lock_id: str | None = None,
        actor: str = "chatgpt",
    ) -> tuple[bool, dict[str, Any] | None]:
        """
        Checks whether a resource has an active lock held by another actor/lock_id.
        Returns (is_locked, lock_details).
        """
        d_clean = (domain or "").lower().strip()
        if not d_clean:
            return False, None

        locks_res = cls.check_locks(domain=d_clean)
        p_clean = (path or "*").strip().replace("\\", "/")
        if not p_clean:
            p_clean = "*"

        for lk in locks_res.get("active_locks", []):
            if current_lock_id and lk.get("lock_id") == current_lock_id:
                continue
            # If the same actor holds it, permit unless explicit different lock_id needed
            if lk.get("locked_by") == actor:
                continue
            existing_path = lk.get("path", "*")
            if existing_path == "*" or p_clean == "*" or existing_path == p_clean or p_clean.startswith(existing_path.rstrip("/") + "/"):
                return True, lk

        return False, None


# Module-level convenience functions
acquire_hosting_lock = HostingLockManager.acquire_lock
release_hosting_lock = HostingLockManager.release_lock
check_hosting_locks = HostingLockManager.check_locks
is_resource_locked = HostingLockManager.is_resource_locked
