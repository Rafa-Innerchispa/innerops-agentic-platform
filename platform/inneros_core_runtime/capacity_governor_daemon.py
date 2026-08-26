"""Periodic no-LLM capacity sampler for the InnerOS Dev Swarm."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from raphiia_openai import capacity_governor_vnext, dev_swarm_scheduler


def tick() -> dict[str, Any]:
    status = dev_swarm_scheduler.capacity_status()
    maintenance: dict[str, Any] = {}
    maintenance["ollama_baseline"] = capacity_governor_vnext.enforce_ollama_baseline(dry_run=False)
    maintenance["amd_vllm_watchdog"] = capacity_governor_vnext.amd_vllm_watchdog_tick(dry_run=False)
    status["maintenance"] = maintenance
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Run continuously.")
    parser.add_argument("--interval", type=int, default=30, help="Loop interval in seconds.")
    args = parser.parse_args()
    if not args.loop:
        print(json.dumps(tick(), sort_keys=True, default=str))
        return 0
    interval = max(10, int(args.interval or 30))
    while True:
        try:
            tick()
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
