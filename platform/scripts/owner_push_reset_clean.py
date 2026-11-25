#!/usr/bin/env python3
"""Limpia bandeja owner (Mongo inbox) y cierra decisiones canario duplicadas."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

RUNTIME = Path(os.environ.get("INNEROS_PLATFORM_RUNTIME", "/home/rlopez/inneros/inneros_core/platform"))
sys.path = [p for p in sys.path if Path(p).resolve() != RUNTIME.parent]
sys.path.insert(0, str(RUNTIME))

from inneros_core_runtime.coordination_live import OPS_TASKS_COL  # noqa: E402
from raphiia_openai import mongo_store  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Ejecutar borrado (default: dry-run)")
    p.add_argument("--fence-canaries", action="store_true", help="Marcar OPS [CANARIO] antiguas como superseded")
    args = p.parse_args()
    db = mongo_store.get_db()
    inbox = db["ralfia_owner_push_inbox"]
    decisions = db["atlas_ops_owner_decisions"]
    dedupe = db["ralfia_owner_push_dedupe"]
    n_inbox = inbox.count_documents({})
    n_pending = decisions.count_documents({"status": "pending"})
    canaries = list(
        db[OPS_TASKS_COL].find(
            {"title": {"$regex": r"\[CANARIO\]|canary|notify-canary", "$options": "i"}, "status": {"$nin": ["superseded", "cancelled", "completed"]}},
            {"task_id": 1, "title": 1, "status": 1},
        ).limit(50)
    )
    print(f"inbox_messages={n_inbox} pending_decisions={n_pending} open_canaries={len(canaries)}")
    if not args.apply:
        print("Dry-run. Usa --apply para limpiar.")
        return 0
    inbox.delete_many({})
    dedupe.delete_many({})
    now = time.time()
    decisions.update_many(
        {"status": "pending"},
        {"$set": {"status": "expired", "updated_at": now, "decided_by": "owner_push_reset"}},
    )
    if args.fence_canaries:
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).isoformat()
        for row in canaries:
            db[OPS_TASKS_COL].update_one({"task_id": row["task_id"]}, {"$set": {"status": "superseded", "updated_at": ts}})
            print("fenced", row.get("task_id"), row.get("title", "")[:60])
    print("OK: bandeja limpia (Mongo). En el celular: ntfy → mantén pulsado topic → borrar notificaciones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())