#!/usr/bin/env python3
"""Archive stale interactive OPS (Cursor/Codex/Antigravity) — coordination queue to zero."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INTERACTIVE = frozenset({"cursor", "codex", "antigravity", "gemini", "chatgpt"})
TERMINAL = frozenset({"completed", "done", "cancelled", "canceled", "superseded", "archived"})
STALE_TITLE = re.compile(
    r"cross-smoke|quad-canary|rev-parse|competencia/externo|cursor-ha-e2e|smoke|canary|autonomous repair",
    re.I,
)
# Codex HA Companion (#227) — no anular; el resto del carril web vive en inbox Codex.
DEFAULT_PROTECT_TASK_IDS = frozenset({"ops_d7ac9d1e90ec"})


def _protect_ids() -> frozenset[str]:
    raw = (os.getenv("INNEROS_OPS_HYGIENE_PROTECT_TASK_IDS") or "").strip()
    extra = {x.strip() for x in raw.split(",") if x.strip()}
    return DEFAULT_PROTECT_TASK_IDS | extra


def _keep_task(task: dict, *, protect: frozenset[str]) -> bool:
    tid = str(task.get("task_id") or "")
    if tid in protect:
        return True
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Ejecutar supersede (sin esto solo dry-run)")
    args = parser.parse_args()
    dry_run = not args.apply

    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from inneros_core_runtime import interactive_provider_lanes as ipl
    from raphiia_openai import mongo_store

    protect = _protect_ids()
    db = mongo_store.get_db()
    col = db[OPS_TASKS_COL]
    filt = {
        "assignee": {"$in": sorted(INTERACTIVE)},
        "status": {"$nin": sorted(TERMINAL)},
    }
    rows = list(col.find(filt, {"_id": 0}))
    archived = []
    kept = []
    for task in rows:
        tid = str(task.get("task_id") or "")
        title = str(task.get("title") or "")
        status = str(task.get("status") or "")
        if _keep_task(task, protect=protect):
            kept.append({"task_id": tid, "status": status, "title": title[:80], "reason": "protected"})
            continue
        reason = "coordination_cleanup_owner_request"
        if STALE_TITLE.search(title):
            reason = "stale_canary_or_smoke"
        updates = {
            "$set": {
                "status": "superseded",
                "superseded_at": _now(),
                "superseded_by": "ops_queue_hygiene_zero_pending",
                "superseded_reason": reason,
                "last_progress": "Superseded — cola IDE limpiada (HA Companion activo)",
                "updated_at": _now(),
                "do_not_auto_dispatch": True,
            },
            "$unset": {
                "claim_token": "",
                "claimed_at": "",
                "claim_host": "",
                "headless_execution_started_at": "",
                "headless_execution_finished_at": "",
                "headless_execution_pid": "",
                "headless_execution_host": "",
                "antigravity_headless_started_at": "",
                "provider_execution_started_at": "",
                "provider_execution_host": "",
                "provider_execution_finished_at": "",
                "lease_until": "",
            },
            "$inc": {"revision": 1},
        }
        if not dry_run:
            col.update_one({"task_id": tid}, updates)
        archived.append({"task_id": tid, "prior_status": status, "title": title[:80], "reason": reason})

    lane_reconcile = ipl.reconcile_stale_provider_lanes(dry_run=dry_run)

    remaining = col.count_documents(filt)
    out = {
        "ok": True,
        "dry_run": dry_run,
        "archived_count": len(archived),
        "kept_count": len(kept),
        "protected_task_ids": sorted(protect),
        "kept_sample": kept[:20],
        "remaining_non_terminal_interactive": remaining,
        "archived_sample": archived[:30],
        "lane_reconcile": lane_reconcile,
    }
    evidence = ROOT.parent / "var" / "evidence" / "ops_queue_hygiene_zero_pending.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
