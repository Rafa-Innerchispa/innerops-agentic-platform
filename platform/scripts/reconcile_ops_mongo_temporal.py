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
        from temporalio.client import WorkflowExecutionStatus

        raw_status = desc.status
        if isinstance(raw_status, int):
            try:
                status_name = WorkflowExecutionStatus(raw_status).name
            except ValueError:
                status_name = str(raw_status)
        else:
            status_name = str(getattr(raw_status, "name", raw_status))
        terminal = status_name in {
            "COMPLETED",
            "FAILED",
            "TERMINATED",
            "CANCELED",
            "CANCELLED",
        } or any(x in status_name for x in ("COMPLETED", "FAILED", "TERMINATED", "CANCELED", "CANCELLED"))
        result_status = None
        result_gate_passed = None
        if "COMPLETED" in status_name:
            # The RPC workflow may COMPLETE while returning {"status": "failed"}.
            result = await handle.result()
            if isinstance(result, dict):
                result_status = str(result.get("status") or "").strip().lower() or None
                evidence = result.get("evidence") or {}
                gate = evidence.get("gate_verification") if isinstance(evidence, dict) else None
                if isinstance(gate, dict):
                    result_gate_passed = gate.get("passed") is True
        return {
            "ok": True, "workflow_id": workflow_id, "status": status_name,
            "run_id": desc.run_id, "terminal": terminal,
            "result_status": result_status, "result_gate_passed": result_gate_passed,
        }
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
    # Never mark tasks failed merely because Temporal is temporarily unreachable.
    # A lease timeout is not proof that an external process stopped.
    if not temporal.get("ok") or not temporal.get("terminal"):
        return None
    st = str(temporal.get("status") or "").upper()
    if any(x in st for x in ("FAILED", "TERMINATED")):
        new_status = "failed"
    elif "CANCELED" in st:
        new_status = "cancelled"
    elif "COMPLETED" in st:
        outcome = str(temporal.get("result_status") or "").lower()
        if outcome in {"failed", "cancelled"}:
            new_status = outcome
        elif outcome == "completed":
            is_coding = str(task.get("task_class") or "coding").lower() == "coding"
            if is_coding and temporal.get("result_gate_passed") is not True:
                return None
            # Never write terminal completed from reconcile — global gate + verified_receipt only.
            new_status = "verification"
        else:
            # A successful Temporal RPC can carry a blocked or failed task.
            # Unknown legacy result shape must be reviewed, not completed.
            return None
    else:
        return None
    return {
        "task_id": tid,
        "action": "set_status",
        "new_status": new_status,
        "reason": "temporal_result_verified_mongo_stale",
        "temporal": temporal,
    }


def _siblings_by_supersedes(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        target = str(row.get("supersedes_task_id") or "").strip()
        if target:
            index.setdefault(target, []).append(row)
    return index


def _proposed_superseded(task: dict[str, Any], siblings: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Close a lease-expired claim that a newer linked task replaced.

    Never force-closes a lone claim: without a live (non-terminal) sibling
    carrying supersedes_task_id -> this task, returns None and leaves the row
    for liveness/human review. Mirrors the dev_swarm_watchdog superseded
    shape (status + superseded_by/at/by_actor), preserving history.
    """
    tid = str(task.get("task_id") or "").strip()
    if not tid or str(task.get("status") or "") != "claimed":
        return None
    if not _lease_expired(task):
        return None
    live = [
        s for s in (siblings or [])
        if s is not task
        and str(s.get("supersedes_task_id") or "").strip() == tid
        and str(s.get("status") or "") not in TERMINAL_MONGO
    ]
    if not live:
        return None
    newer = sorted(live, key=lambda s: str(s.get("created_at") or s.get("updated_at") or ""))[-1]
    nid = str(newer.get("task_id") or "").strip()
    if not nid:
        return None
    now = _utc()
    return {
        "task_id": tid,
        "action": "set_status",
        "new_status": "superseded",
        "reason": f"lease_expired_superseded_by_{nid}",
        "superseded_by": nid,
        "superseded_at": now,
        "superseded_by_actor": "reconcile_ops_mongo_temporal",
    }


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
    supersede_index = _siblings_by_supersedes(rows)
    for doc in rows:
        tid = str(doc.get("task_id") or "")
        wf = str(doc.get("workflow_id") or f"ops_task:{tid}")
        temporal = asyncio.run(_temporal_describe(wf))
        prop = _proposed_action(doc, temporal)
        if prop is None and str(doc.get("status") or "") == "claimed":
            prop = _proposed_superseded(doc, supersede_index.get(tid, []))
        if prop:
            actions.append({**prop, "mongo_status": doc.get("status"), "correlation_id": doc.get("correlation_id")})

    applied = 0
    skipped_concurrent_updates = 0
    if args.apply:
        now = _utc()
        for act in actions:
            # CAS: a claim/lease/terminal state that moved since the scan wins.
            prior = next((row for row in rows if row.get("task_id") == act["task_id"]), {})
            filt = {"task_id": act["task_id"], "status": act["mongo_status"]}
            if "revision" in prior:
                filt["revision"] = prior["revision"]
            if "lease_until" in prior:
                filt["lease_until"] = prior["lease_until"]
            change = col.update_one(
                filt,
                {
                    "$set": {
                        "status": act["new_status"],
                        "updated_at": now,
                        "reconcile_note": act["reason"],
                        "reconcile_at": now,
                        "reconcile_evidence": {"temporal": act.get("temporal"), "by": "reconcile_ops_mongo_temporal.py"},
                        **{k: act[k] for k in ("superseded_by", "superseded_at", "superseded_by_actor") if k in act},
                    },
                    "$inc": {"revision": 1},
                },
            )
            if getattr(change, "modified_count", 0) == 1:
                applied += 1
            else:
                skipped_concurrent_updates += 1

    report = {
        "ok": True,
        "generated_at": _utc(),
        "scanned": len(rows),
        "proposed": len(actions),
        "applied": applied,
        "skipped_concurrent_updates": skipped_concurrent_updates,
        "dry_run": not args.apply,
        "actions": actions,
    }
    out_path = os.path.join(
        os.getenv("INNEROS_RECONCILE_EVIDENCE_DIR", "/home/rlopez/inneros/inneros_core/var/evidence"),
        "ops_mongo_temporal_reconcile.json",
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps({"ok": True, "path": out_path, "proposed": len(actions), "applied": applied}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
