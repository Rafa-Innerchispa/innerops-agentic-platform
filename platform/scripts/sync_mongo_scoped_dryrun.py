"""Scoped Mongo sync DRY-RUN (AMD <-> Intel). Read-only by construction.

Compares live coordination state on both nodes and prints the merge manifest
that a future apply mode would execute. This module performs ZERO writes:
no update/insert/delete calls exist in this file (asserted by test).

Usage:
    PYTHONPATH=platform python3 platform/scripts/sync_mongo_scoped_dryrun.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

TERMINAL_STATUSES = frozenset({
    "completed", "failed", "cancelled", "canceled", "superseded", "archived",
})

TASKS_COLLECTION = "ralfia_ops_tasks"
MESSAGES_COLLECTION = "ralfia_agent_messages"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _EPOCH


def _content_hash(doc: dict[str, Any]) -> str:
    body = {k: v for k, v in doc.items() if k not in {"_id", "synced_at", "synced_from"}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _doc_key(doc: dict[str, Any], collection: str) -> str:
    if collection == MESSAGES_COLLECTION:
        return str(doc.get("message_id") or "")
    return str(doc.get("task_id") or "")


def _doc_revision(doc: dict[str, Any]) -> int:
    try:
        return int(doc.get("revision") or 0)
    except (TypeError, ValueError):
        return 0


def compare_pair(local: dict[str, Any] | None, remote: dict[str, Any] | None,
                 collection: str) -> dict[str, Any]:
    """Decide the sync action for one document present on either side.

    Returns {"action": "in_sync"|"push"|"pull"|"conflict"|"flag_terminal_mismatch",
    ...}. Pure function (no I/O) so the merge rules are unit-testable.
    """
    if local is None and remote is None:
        return {"action": "in_sync", "reason": "absent_both"}
    if local is None:
        return {"action": "pull", "reason": "missing_local"}
    if remote is None:
        return {"action": "push", "reason": "missing_remote"}
    if _content_hash(local) == _content_hash(remote):
        return {"action": "in_sync", "reason": "identical_content"}
    rev_l, rev_r = _doc_revision(local), _doc_revision(remote)
    ts_l, ts_r = _parse_ts(local.get("updated_at")), _parse_ts(remote.get("updated_at"))
    if collection == TASKS_COLLECTION:
        term_l = str(local.get("status") or "").lower() in TERMINAL_STATUSES
        term_r = str(remote.get("status") or "").lower() in TERMINAL_STATUSES
        if term_l != term_r:
            return {"action": "flag_terminal_mismatch",
                    "reason": f"local={local.get('status')}/remote={remote.get('status')}",
                    "local_rev": rev_l, "remote_rev": rev_r}
    if (rev_r, ts_r) > (rev_l, ts_l):
        return {"action": "pull", "reason": "remote_newer",
                "local_rev": rev_l, "remote_rev": rev_r}
    if (rev_l, ts_l) > (rev_r, ts_r):
        return {"action": "push", "reason": "local_newer",
                "local_rev": rev_l, "remote_rev": rev_r}
    return {"action": "conflict", "reason": "same_version_different_content",
            "local_rev": rev_l, "remote_rev": rev_r}


def _fetch_live_tasks(db: Any) -> dict[str, dict[str, Any]]:
    rows = db[TASKS_COLLECTION].find({}, {"_id": 0})
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").lower() in TERMINAL_STATUSES:
            continue
        key = _doc_key(row, TASKS_COLLECTION)
        if key:
            out[key] = row
    return out


def _fetch_open_messages(db: Any, limit: int = 2000) -> dict[str, dict[str, Any]]:
    rows = db[MESSAGES_COLLECTION].find(
        {"status": {"$in": ["open", "sending"]}}, {"_id": 0}).limit(limit)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _doc_key(row, MESSAGES_COLLECTION)
        if key:
            out[key] = row
    return out


def compute_manifest(amd_db: Any, intel_db: Any) -> dict[str, Any]:
    """Compare both nodes. Reads only. Never writes."""
    manifest: dict[str, Any] = {"collections": {}, "totals": {"push": 0, "pull": 0, "conflict": 0,
                                                              "flag_terminal_mismatch": 0, "in_sync": 0}}
    jobs = [("tasks", TASKS_COLLECTION, _fetch_live_tasks),
            ("messages", MESSAGES_COLLECTION, _fetch_open_messages)]
    for label, collection, fetch in jobs:
        try:
            local_docs, remote_docs = fetch(amd_db), fetch(intel_db)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the manifest
            manifest["collections"][label] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
            continue
        entry: dict[str, Any] = {"ok": True, "amd_count": len(local_docs), "intel_count": len(remote_docs),
                                 "actions": {}, "samples": {}}
        buckets: dict[str, list[str]] = {}
        for key in sorted(set(local_docs) | set(remote_docs)):
            verdict = compare_pair(local_docs.get(key), remote_docs.get(key), collection)
            action = verdict["action"]
            buckets.setdefault(action, []).append(key)
            manifest["totals"][action] = manifest["totals"].get(action, 0) + 1
        for action, keys in buckets.items():
            entry["actions"][action] = len(keys)
            entry["samples"][action] = keys[:8]
        manifest["collections"][label] = entry
    return manifest


def main() -> int:
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from pymongo import MongoClient

    try:
        amd = MongoClient("mongodb://127.0.0.1:27017/", serverSelectionTimeoutMS=8000)["pcdoctor_swarm"]
        intel = MongoClient("mongodb://192.168.1.4:27017/", serverSelectionTimeoutMS=8000)["pcdoctor_swarm"]
        amd.client.admin.command("ping")
        intel.client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"mongo_unreachable: {exc}"[:200]}))
        return 2
    manifest = compute_manifest(amd, intel)
    manifest["ok"] = True
    manifest["mode"] = "dry_run_read_only"
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(manifest, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
