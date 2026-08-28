#!/usr/bin/env python3
"""Timer AG-50: brief diario local (Ollama + memoria)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    from raphiia_openai.agents import ag50_daily_companion as ag50

    result = ag50.run_daily_companion("", include_brief=True)
    print("ok=", result.get("ok"), "brief=", bool(result.get("brief")), "memory=", result.get("memory_hits"))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
