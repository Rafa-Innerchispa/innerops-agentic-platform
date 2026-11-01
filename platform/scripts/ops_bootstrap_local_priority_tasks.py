#!/usr/bin/env python3
"""Promote protected P1 local tasks (WordPress, Gmail) to Dev Swarm proposed — no IDE credits."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOCAL_TASKS: dict[str, dict] = {
    "ops_446a47bf778d": {
        "title": "WordPress Page Builder fase 1 | implementar código y tests locales",
        "objective": "Implementar fase 1 WordPress Page Builder con tests locales en platform/",
    },
    "ops_e8c6e290c53f": {
        "title": "P1 corregir vigilancia Gmail: oportunidades humanas y señales estratégicas",
        "objective": (
            "Corregir vigilancia Gmail en platform/ ONLY: editar "
            "platform/inneros_core_runtime/notifications/email_intelligence.py, "
            "platform/raphiia_openai/notifications/email_router.py si aplica, y "
            "platform/tests/test_email_intelligence*.py. "
            "NO crear rutas bajo src/agents_pool ni imports con AG-05 en el path Python. "
            "Añadir reglas para oportunidades humanas (XERJ, hackathons, 2FA) y alertas HA. "
            "Tests unittest bajo platform/tests."
        ),
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bootstrap(*, dry_run: bool = True) -> dict:
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from inneros_core_runtime import ops_task_admission as ota
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    col = db[OPS_TASKS_COL]
    out: list[dict] = []
    for tid, spec in LOCAL_TASKS.items():
        row = col.find_one({"task_id": tid}, {"_id": 0}) or {}
        if not row:
            out.append({"task_id": tid, "ok": False, "error": "not_found"})
            continue
        if str(row.get("status") or "") in {"completed", "partial"} and tid == "ops_446a47bf778d":
            out.append({"task_id": tid, "ok": True, "dry_run": dry_run, "skipped": "already_completed_wordpress"})
            continue
        payload = dict(row.get("payload") or {})
        payload.update(
            {
                "repo": payload.get("repo") or "Rafa-Innerchispa/innerops-agentic-platform",
                "related_project": payload.get("related_project") or "Rafa-Innerchispa/innerops-agentic-platform",
                "task_class": payload.get("task_class") or "ops",
                "assignee": "dev_swarm",
                "preferred_provider": "local-intel-4",
                "provider_transport": "local_dev_swarm",
                "execution_lane": "local_dev_swarm",
                "runtime_profile": payload.get("runtime_profile") or "python-tests",
                "base_ref": payload.get("base_ref") or "main",
                "do_not_auto_dispatch": False,
                "owner_approved": True,
                "objective": spec["objective"],
            }
        )
        patch = ota.normalize_ops_admission(
            {
                **row,
                "task_id": tid,
                "objective": spec["objective"],
                "title": row.get("title") or spec["title"],
                "assignee": "dev_swarm",
                "status": "proposed",
                "priority": row.get("priority") or "high",
                "payload": payload,
                "owner_authorized_at": row.get("owner_authorized_at") or _now(),
                "owner_actor": row.get("owner_actor") or os.getenv("RALFIA_OWNER_ID") or "INNEROS_LOCAL_BOOTSTRAP",
                "dev_swarm_retry_requested": True,
                "coordination_relevance": "keep",
                "execution_lane": "local_dev_swarm",
                "task_class": "ops",
                "updated_at": _now(),
            }
        )
        patch["execution_lane"] = "local_dev_swarm"
        if not dry_run:
            patch.pop("revision", None)
            col.update_one({"task_id": tid}, {"$set": patch, "$inc": {"revision": 1}})
        out.append(
            {
                "task_id": tid,
                "ok": True,
                "dry_run": dry_run,
                "status": patch.get("status"),
                "assignee": patch.get("assignee"),
                "execution_lane": (patch.get("payload") or {}).get("execution_lane"),
            }
        )
    return {"ok": True, "dry_run": dry_run, "tasks": out}


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dispatch", action="store_true", help="Tras bootstrap, scheduler_tick local (1 tarea)")
    args = p.parse_args()
    report = bootstrap(dry_run=not args.apply)
    if args.apply and args.dispatch:
        from inneros_core_runtime import dev_swarm_scheduler as dss

        tick = dss.scheduler_tick(limit=int(os.getenv("DEV_SWARM_TICK_LIMIT", "2")), dry_run=False)
        report["scheduler_tick"] = {
            k: tick.get(k)
            for k in ("ok", "selected", "skipped", "filtered", "filtered_count", "node")
            if k in tick or tick.get(k) is not None
        }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
