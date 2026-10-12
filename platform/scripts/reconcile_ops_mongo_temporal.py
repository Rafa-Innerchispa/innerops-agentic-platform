#!/usr/bin/env python3
"""Reconcile non-terminal Mongo ops vs Temporal (safe). Default dry-run; --apply writes."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TERMINAL_MONGO = frozenset({"completed", "failed", "cancelled", "superseded", "done"})
STALE_CORRELATION_PREFIXES = ("golden-flow", "co_cursor_ha_e2e", "quad-lane-canary")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_expired(task: dict[str, Any]) -> bool:
    lease = str(task.get("lease_until") or "").strip()
    return bool(lease) and lease < _utc()


async def _temporal_describe(workflow_id: str) -> dict[str, Any]:
    try:
        from temporalio.client import Client

        client = await Client.connect(
            os.getenv("TEMPORAL_HOST", "127.0.0.1:7233"),
            namespace=os.getenv("INNEROS_TEMPORAL_NAMESPACE", "default"),
        )
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        status_name = str(desc.status)
        terminal = any(x in status_name for x in ("COMPLETED", "FAILED", "TERMINATED", "CANCELED"))
        return {"ok": True, "workflow_id": workflow_id, "status": status_name, "run_id": desc.run_id, "terminal": terminal}
    except Exception as exc:
        return {"ok": False, "workflow_id": workflow_id, "error": type(exc).__name__, "detail": str(exc)[:240]}


def _is_stale_canary(task: dict[str, Any]) -> bool:
    corr = str(task.get("correlation_id") or "")
    return any(corr.startswith(p) for p in STALE_CORRELATION_PREFIXES)


def _proposed_action(task: dict[str, Any], temporal: dict[str, Any]) -> dict[str, Any] | None:
    mongo_status = str(task.get("status") or "")
    if mongo_status in TERMINAL_MONGO:
        return None
    tid = str(task.get("task_id") or "")
    wf_id = str(task.get("workflow_id") or f"ops_task:{tid}")
    headless_done = bool(task.get("headless_execution_finished_at"))
    stale_canary = _is_stale_canary(task)
    if not temporal.get("ok"):
        if stale_canary or headless_done or _lease_expired(task):
            return {
                "task_id": tid,
                "action": "set_status",
                "new_status": "superseded" if stale_canary else "failed",
                "reason": "temporal_workflow_missing",
                "temporal": temporal,
            }
        return None
    if temporal.get("terminal"):
        st = str(temporal.get("status") or "")
        new_status = "failed" if any(x in st for x in ("FAILED", "TERMINATED", "CANCELED")) else "completed"
        return {
            "task_id": tid,
            "action": "set_status",
            "new_status": new_status,
            "reason": "temporal_terminal_mongo_stale",
            "temporal": temporal,
        }
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--task-id", action="append", default=[])
    args = parser.parse_args()

    from raphiia_openai import mongo_store
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL

    db = mongo_store.get_db()
    col = db[OPS_TASKS_COL]
    filt: dict[str, Any] = {"status": {"$nin": sorted(TERMINAL_MONGO)}}
    if args.task_id:
        filt = {"task_id": {"$in": [t.strip() for t in args.task_id if t.strip()]}}

    rows = list(col.find(filt, {"_id": 0}).sort("updated_at", 1).limit(max(1, min(args.limit, 200))))
    actions: list[dict[str, Any]] = []
    for doc in rows:
        tid = str(doc.get("task_id") or "")
        wf = str(doc.get("workflow_id") or f"ops_task:{tid}")
        temporal = asyncio.run(_temporal_describe(wf))
        prop = _proposed_action(doc, temporal)
        if prop:
            actions.append({**prop, "mongo_status": doc.get("status"), "correlation_id": doc.get("correlation_id")})

    applied = 0
    if args.apply:
        now = _utc()
        for act in actions:
            col.update_one(
                {"task_id": act["task_id"], "status": {"$nin": sorted(TERMINAL_MONGO)}},
                {
                    "$set": {
                        "status": act["new_status"],
                        "updated_at": now,
                        "reconcile_note": act["reason"],
                        "reconcile_at": now,
                        "reconcile_evidence": {"temporal": act.get("temporal"), "by": "reconcile_ops_mongo_temporal.py"},
                    },
                    "$inc": {"revision": 1},
                },
            )
            applied += 1

    report = {
        "ok": True,
        "generated_at": _utc(),
        "scanned": len(rows),
        "proposed": len(actions),
        "applied": applied,
        "dry_run": not args.apply,
        "actions": actions,
    }
    out_path = "/home/rlopez/inneros/inneros_core/var/evidence/ops_mongo_temporal_reconcile.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps({"ok": True, "path": out_path, "proposed": len(actions), "applied": applied}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
