#!/usr/bin/env python3
"""Reprocesa votos de encuesta ops ya guardados en Mongo (p. ej. portal sin parser)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _norm_phone(sender: str) -> str:
    return "".join(c for c in str(sender or "") if c.isdigit())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2026-10-08T17:00:00+00:00")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from raphiia_openai import mongo_store, whatsapp_evolution_parse as evo
    from raphiia_openai.notifications.evolution_client import send_whatsapp
    from inneros_core_runtime import ops_whatsapp_owner as ops_wa

    db = mongo_store.get_db()
    cursor = db.whatsapp_inbound_events.find(
        {
            "received_at": {"$gte": args.since},
            "raw.data.message.pollUpdateMessage": {"$exists": True},
        },
        {"raw": 1, "received_at": 1},
    ).sort("received_at", 1)

    processed = 0
    for doc in cursor:
        raw = doc.get("raw") or {}
        cmd = evo.extract_message(raw) or evo.extract_poll_ops_auth_command(raw)
        if not cmd or not cmd.strip().upper().startswith(("SI ", "NO ", "SÍ ")):
            continue
        sender = evo.extract_sender(raw)
        phone = _norm_phone(sender)
        if args.dry_run:
            print("dry", doc.get("received_at"), cmd, phone)
            processed += 1
            continue
        out = ops_wa.handle_owner_reply(cmd, phone=phone)
        if out is None:
            print("skip", cmd, "no handler")
            continue
        print(doc.get("received_at"), cmd, "->", out.get("ok"), out.get("task_id"), out.get("action"))
        if out.get("text") and phone:
            send_whatsapp(out["text"], number=phone)
        processed += 1
    print("processed", processed)
    return 0 if processed else 1


if __name__ == "__main__":
    raise SystemExit(main())
