#!/usr/bin/env python3
"""Timer AG-36: scan ops deferred + auto-escalado local."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

AUTO = os.getenv("RALFIA_DEFERRED_ESCALATE", "0").strip() in ("1", "true", "yes")


def main() -> int:
    from raphiia_openai.agents import ag36_deferred_tasks_agent as ag36

    if AUTO:
        result = ag36.run_deferred_ops_cycle(auto_escalate=True)
    else:
        result = ag36.run_deferred_ops_scan()
    print("ok=", result.get("ok"), "deferred=", result.get("deferred_count"), "escalated=", len(result.get("escalations") or []))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
