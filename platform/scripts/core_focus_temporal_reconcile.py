#!/usr/bin/env python3
"""Reconcile Mongo ops projection vs Temporal workflows (read-only, msg_b35 gate C)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


async def _temporal_status(workflow_id: str) -> dict:
    try:
        from temporalio.client import Client

        client = await Client.connect(
            os.getenv("TEMPORAL_HOST", "127.0.0.1:7233"),
            namespace=os.getenv("INNEROS_TEMPORAL_NAMESPACE", "default"),
        )
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        return {
            "ok": True,
            "workflow_id": workflow_id,
            "status": str(desc.status),
            "run_id": desc.run_id,
        }
    except Exception as exc:
        return {"ok": False, "workflow_id": workflow_id, "error": type(exc).__name__, "detail": str(exc)[:300]}


def main() -> int:
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    col = db["ralfia_ops_tasks"]
    stale = list(
        col.find({"status": {"$in": ["running", "dispatched"]}}, {"_id": 0})
        .sort("updated_at", 1)
        .limit(20)
    )
    rows = []
    for doc in stale:
        tid = str(doc.get("task_id") or "")
        wf = str(doc.get("workflow_id") or f"ops_task:{tid}")
        temporal = asyncio.run(_temporal_status(wf))
        rows.append(
            {
                "task_id": tid,
                "mongo_status": doc.get("status"),
                "mongo_updated_at": doc.get("updated_at"),
                "correlation_id": doc.get("correlation_id"),
                "temporal": temporal,
            }
        )

    report = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stale_count": len(stale),
        "rows": rows,
        "mutations_applied": False,
    }
    path = "/home/rlopez/inneros/inneros_core/var/evidence/temporal_reconcile_report.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps({"ok": True, "path": path, "stale_count": len(stale)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
