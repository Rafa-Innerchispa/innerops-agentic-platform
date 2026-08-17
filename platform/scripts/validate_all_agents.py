#!/usr/bin/env python3
"""Validación rápida AG-01..54 — ping local sin créditos cloud."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from raphiia_openai.agents.pool_agent_runners import get_runner_registry, invoke_agent


def main() -> int:
    runners = get_runner_registry()
    failed: list[tuple[str, str]] = []
    for aid in sorted(runners.keys(), key=lambda x: int(x.split("-")[1])):
        r = invoke_agent(aid, "", dry_run=True)
        if not r.get("ok"):
            failed.append((aid, str(r.get("error", r))[:100]))
    print(f"agents: {len(runners)} ok: {len(runners) - len(failed)} fail: {len(failed)}")
    for aid, err in failed:
        print(f"  FAIL {aid}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
