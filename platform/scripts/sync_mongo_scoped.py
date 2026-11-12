"""Scoped Mongo sync AMD<->Intel: dry-run manifest + gated apply.

Default mode is read-only dry-run (prints the merge manifest, writes
nothing). Apply mode requires BOTH --apply and --yes, honors the
sync_control kill-switch on either node, never touches conflicts or
terminal-mismatches, and re-verifies every document before writing.

Usage:
    PYTHONPATH=platform python3 platform/scripts/sync_mongo_scoped.py
    PYTHONPATH=platform python3 platform/scripts/sync_mongo_scoped.py --apply --yes [--limit N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from typing import Any

TERMINAL_STATUSES = frozenset({
    "completed", "failed", "cancelled", "canceled", "superseded", "archived",
})

TASKS_COLLECTION = "ralfia_ops_tasks"
MESSAGES_COLLECTION = "ralfia_agent_messages"
CONTROL_COLLECTION = "sync_control"
CONTROL_KEY = "ops_live"

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

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


def _fetch_terminal_counterparts(db: Any, collection: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch terminal-side docs for ids that are live on the other node.

    Without this, a task that is live locally but terminal remotely looks
    merely "missing remote" and would be pushed over the terminal state
    (resurrection). Client-side filtering keeps this mock-robust.
    """
    wanted = {i for i in ids if i}
    if collection != TASKS_COLLECTION or not wanted:
        return {}
    try:
        rows = db[collection].find(
            {"task_id": {"$in": sorted(wanted)}, "status": {"$in": sorted(TERMINAL_STATUSES)}},
            {"_id": 0},
        )
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = _doc_key(row, collection)
        if not key or key not in wanted:
            continue
        if str(row.get("status") or "").lower() not in TERMINAL_STATUSES:
            continue
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
        if label == "tasks":
            local_docs = {**_fetch_terminal_counterparts(amd_db, collection,
                                                           [k for k in remote_docs if k not in local_docs]),
                          **local_docs}
            remote_docs = {**_fetch_terminal_counterparts(intel_db, collection,
                                                            [k for k in local_docs if k not in remote_docs]),
                           **remote_docs}
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
        entry["_local_docs"] = local_docs
        entry["_remote_docs"] = remote_docs
    return manifest


def kill_switch_engaged(amd_db: Any, intel_db: Any) -> tuple[bool, str]:
    """True when either node explicitly disabled the sync. Missing doc = enabled."""
    for name, db in (("amd", amd_db), ("intel", intel_db)):
        try:
            row = db[CONTROL_COLLECTION].find_one({"_id": CONTROL_KEY}, {"_id": 0}) or {}
        except Exception:
            continue
        if row.get("enabled") is False:
            return True, f"disabled on {name}"
    return False, ""


def apply_manifest(amd_db: Any, intel_db: Any, manifest: dict[str, Any], *,
                   limit: int = DEFAULT_LIMIT, directions: tuple[str, ...] = ("push", "pull"),
                   now_iso: str | None = None) -> dict[str, Any]:
    """Execute push/pull actions. Skips conflicts + terminal mismatches, always.

    Re-verifies every document against fresh reads before writing (stale
    plans are skipped, never forced). Returns per-action results.
    """
    stamp = now_iso or datetime.now(timezone.utc).isoformat()
    summary: dict[str, Any] = {"applied": [], "skipped": [], "errors": [],
                               "blocked": {"conflict": [], "flag_terminal_mismatch": []}}
    remaining = max(1, min(int(limit), MAX_LIMIT))
    for label, collection in (("tasks", TASKS_COLLECTION), ("messages", MESSAGES_COLLECTION)):
        entry = (manifest.get("collections") or {}).get(label) or {}
        if not entry.get("ok", True):
            continue
        local_docs = entry.get("_local_docs") or {}
        remote_docs = entry.get("_remote_docs") or {}
        for key in sorted(set(local_docs) | set(remote_docs)):
            if remaining <= 0:
                summary.setdefault("truncated", True)
                return summary
            verdict = compare_pair(local_docs.get(key), remote_docs.get(key), collection)
            action = verdict["action"]
            if action in ("conflict", "flag_terminal_mismatch"):
                summary["blocked"][action].append(key)
                continue
            if action == "in_sync":
                continue
            if action not in directions:
                continue
            try:
                if action == "push":
                    src = amd_db[collection].find_one(_key_filter(collection, key), {"_id": 0})
                    dst_db, dst_col = intel_db, collection
                else:
                    src = intel_db[collection].find_one(_key_filter(collection, key), {"_id": 0})
                    dst_db, dst_col = amd_db, collection
                if not isinstance(src, dict):
                    summary["skipped"].append({"key": key, "reason": "source_vanished"})
                    continue
                other_side = remote_docs.get(key) if action == "push" else local_docs.get(key)
                recheck = (compare_pair(src, other_side, collection) if action == "push"
                           else compare_pair(other_side, src, collection))
                if recheck["action"] != action:
                    summary["skipped"].append({"key": key, "reason": f"stale_plan_now_{recheck['action']}"})
                    continue
                body = {k: v for k, v in src.items() if k != "_id"}
                body["synced_at"] = stamp
                body["synced_from"] = "amd" if action == "push" else "intel"
                dst_db[dst_col].update_one(_key_filter(collection, key), {"$set": body}, upsert=True)
                summary["applied"].append({"key": key, "action": action, "collection": label})
                remaining -= 1
            except Exception as exc:  # noqa: BLE001 - one bad doc never aborts the batch
                summary["errors"].append({"key": key, "error": f"{type(exc).__name__}: {exc}"[:200]})
    return summary


def _key_filter(collection: str, key: str) -> dict[str, str]:
    if collection == MESSAGES_COLLECTION:
        return {"message_id": key}
    return {"task_id": key}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scoped Mongo sync AMD<->Intel (dry-run default).")
    parser.add_argument("--apply", action="store_true",
                        help="execute writes (requires --yes, honors kill-switch, skips divergences)")
    parser.add_argument("--yes", action="store_true",
                        help="explicit live-write confirmation (required with --apply)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"max applied actions (default {DEFAULT_LIMIT}, cap {MAX_LIMIT})")
    parser.add_argument("--directions", default="push,pull",
                        help="comma subset of push (AMD->Intel),pull (Intel->AMD)")
    return parser


def main(argv: list[str] | None = None) -> int:
    from pymongo import MongoClient

    args = build_parser().parse_args(argv)
    directions = tuple(d.strip() for d in str(args.directions or "").split(",") if d.strip())
    if args.apply and not args.yes:
        print(json.dumps({"ok": False, "error": "apply_requires_--yes"}))
        return 2
    if args.apply and (not directions or set(directions) - {"push", "pull"}):
        print(json.dumps({"ok": False, "error": "invalid_directions"}))
        return 2
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
    manifest["mode"] = "apply" if args.apply else "dry_run_read_only"
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    if not args.apply:
        print(json.dumps(manifest, indent=1, default=str))
        return 0
    engaged, detail = kill_switch_engaged(amd, intel)
    if engaged:
        print(json.dumps({"ok": False, "error": "killed_by_sync_control", "detail": detail}))
        return 3
    summary = apply_manifest(amd, intel, manifest, limit=args.limit, directions=directions)
    manifest["apply"] = summary
    print(json.dumps(manifest, indent=1, default=str))
    if summary["blocked"]["conflict"] or summary["blocked"]["flag_terminal_mismatch"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
