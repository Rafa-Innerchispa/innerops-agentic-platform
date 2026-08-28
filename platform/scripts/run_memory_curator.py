#!/usr/bin/env python3
"""CLI Memory Curator — batch, daemon, fleet status o system test."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import memory_curator  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Memory Curator — Drive/Notion → Mongo")
    ap.add_argument("--daemon", action="store_true", help="Loop persistente")
    ap.add_argument("--once", action="store_true", help="Un batch y salir")
    ap.add_argument("--status", action="store_true", help="Estado checkpoint worker actual")
    ap.add_argument("--fleet-status", action="store_true", help="Estado agregado flota")
    ap.add_argument("--search-records", metavar="QUERY", help="Buscar solo registros canonical VKR")
    ap.add_argument("--system-test", action="store_true", help="Prueba búsqueda VKR estricta")
    ap.add_argument("--limit", type=int, default=10, help="Archivos por batch")
    ap.add_argument("--interval", type=int, default=int(os.getenv("MEMORY_CURATOR_INTERVAL", "5")))
    ap.add_argument("--batch-size", type=int, default=int(os.getenv("MEMORY_CURATOR_BATCH_SIZE", "3")))
    ap.add_argument("--worker-id", type=int, default=int(os.getenv("MEMORY_CURATOR_WORKER_ID", "0")))
    ap.add_argument("--num-workers", type=int, default=int(os.getenv("MEMORY_CURATOR_NUM_WORKERS", "1")))
    ap.add_argument("--no-resume", action="store_true", help="Ignorar checkpoint parcial")
    ap.add_argument("--roots", nargs="*", default=None)
    args = ap.parse_args()

    os.environ["MEMORY_CURATOR_WORKER_ID"] = str(args.worker_id)
    os.environ["MEMORY_CURATOR_NUM_WORKERS"] = str(args.num_workers)
    memory_curator.WORKER_ID = args.worker_id
    memory_curator.NUM_WORKERS = max(1, args.num_workers)
    memory_curator.WORKER_LABEL = os.getenv("MEMORY_CURATOR_WORKER_LABEL", f"w{args.worker_id}")

    state_path, log_path = memory_curator.worker_paths(args.worker_id)

    if args.fleet_status:
        print(json.dumps(memory_curator.fleet_status(), indent=2, default=str))
        return

    if args.search_records:
        from raphiia_openai import memory_record_store

        print(json.dumps(memory_record_store.search_records(args.search_records), indent=2, default=str))
        return

    if args.system_test:
        print(json.dumps(memory_curator.run_system_test(), indent=2, default=str))
        return

    if args.status:
        print(json.dumps(memory_curator.status(state_path), indent=2, default=str))
        return

    if args.daemon:
        memory_curator.run_daemon(
            interval=args.interval,
            batch_size=args.batch_size,
            state_path=state_path,
            log_path=log_path,
        )
        return

    result = memory_curator.run_batch(
        limit=args.limit,
        resume=not args.no_resume,
        roots=args.roots,
        state_path=state_path,
        log_path=log_path,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
