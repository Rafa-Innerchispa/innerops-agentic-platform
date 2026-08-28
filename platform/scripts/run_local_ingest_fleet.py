#!/usr/bin/env python3
"""Flota ingesta local — PST (Intel/readpst) + email VKR (Ollama) en loop hasta vaciar cola."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--email-limit", type=int, default=50)
    p.add_argument("--chatgpt-limit", type=int, default=0, help="0 = omitir ChatGPT")
    p.add_argument("--max-cycles", type=int, default=500)
    p.add_argument("--sleep", type=int, default=60, help="Segundos entre ciclos (mínimo)")
    p.add_argument("--idle-backoff-max", type=int, default=1800, help="Máx segundos si processed=0 repetido")
    p.add_argument("--pst-only", action="store_true")
    p.add_argument("--vkr-only", action="store_true")
    p.add_argument("--worker-id", default=os.getenv("INGEST_WORKER_ID", "default"))
    p.add_argument("--worker-shard", type=int, default=int(os.getenv("INGEST_WORKER_SHARD", "0")))
    p.add_argument("--worker-shards", type=int, default=int(os.getenv("INGEST_WORKER_SHARDS", "1")))
    p.add_argument("--pst-per-cycle", type=int, default=1)
    args = p.parse_args()

    from raphiia_openai import ingest_pipeline

    log_suffix = args.worker_id.replace("/", "_")
    log_path = f"/home/rlopez/data/logs/local_ingest_fleet_{log_suffix}.jsonl"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def _log(event: dict) -> None:
        event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        event["worker_id"] = args.worker_id
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
        print(json.dumps(event, default=str)[:4000], flush=True)

    cycles = 0
    idle_streak = 0
    while cycles < args.max_cycles:
        cycles += 1
        cycle: dict = {"cycle": cycles}

        if not args.vkr_only:
            pst = ingest_pipeline.ingest_pst_files(
                dry_run=args.dry_run,
                max_pst=args.pst_per_cycle,
                worker_id=args.worker_id,
            )
            cycle["pst"] = {
                k: pst.get(k)
                for k in (
                    "pst_found",
                    "pst_pending",
                    "pst_processed",
                    "pst_remaining",
                    "imported",
                    "current_pst",
                    "ok",
                    "error",
                )
            }

        if not args.pst_only:
            if args.chatgpt_limit > 0:
                cycle["chatgpt"] = ingest_pipeline.import_chatgpt_coordination_docs(
                    limit=args.chatgpt_limit,
                    dry_run=args.dry_run,
                )
            cycle["email_vkr"] = ingest_pipeline.ingest_email_vkr_batch(
                limit=args.email_limit,
                dry_run=args.dry_run,
                worker_shard=args.worker_shard,
                worker_shards=args.worker_shards,
            )

        _log(cycle)

        pst_remaining = int((cycle.get("pst") or {}).get("pst_remaining") or 0)
        vkr = cycle.get("email_vkr") or {}
        vkr_pending = int(vkr.get("pending") or 0)
        vkr_active = int(vkr.get("processed") or 0) > 0 or int(vkr.get("skipped") or 0) > 0

        vkr_processed = int(vkr.get("processed") or 0)
        vkr_canonical = int(vkr.get("canonical") or 0)
        if args.vkr_only or not args.pst_only:
            if vkr_processed == 0 and vkr_canonical == 0:
                idle_streak += 1
            else:
                idle_streak = 0

        if args.pst_only:
            if pst_remaining <= 0 and int((cycle.get("pst") or {}).get("pst_processed") or 0) == 0:
                break
        elif args.vkr_only:
            if vkr_pending <= 0 and not vkr_active:
                break
        else:
            if pst_remaining <= 0 and vkr_pending <= 0 and not vkr_active:
                break

        sleep_sec = max(0, args.sleep)
        if idle_streak >= 2:
            sleep_sec = min(args.idle_backoff_max, sleep_sec * (2 ** min(idle_streak - 1, 8)))
            cycle["idle_streak"] = idle_streak
            cycle["sleep_sec"] = sleep_sec
        time.sleep(sleep_sec)

    _log({"done": True, "cycles": cycles})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
