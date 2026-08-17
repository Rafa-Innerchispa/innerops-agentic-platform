#!/usr/bin/env python3
"""Timer AG-42: ciclo guardian + auto-reparación local (Ollama/servidor, sin cloud)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

AUTO = os.getenv("RALFIA_SELF_HEAL", "1").strip() not in ("0", "false", "no")


def main() -> int:
    from raphiia_openai.agents import ag42_service_guardian as ag42

    result = ag42.run_self_heal_cycle(auto_repair=AUTO, max_repairs=2)
    print(result.get("ok"), "repairs=", len(result.get("repairs") or []))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
