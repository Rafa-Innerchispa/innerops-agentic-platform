#!/usr/bin/env python3
"""Drill AG-31 — reinicio controlado + verificación + WhatsApp."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai.agents.registry import seed_mongo_registry  # noqa: E402
from raphiia_openai.recovery_agent import run_recovery_drill  # noqa: E402


def main() -> None:
    seed_mongo_registry()
    result = run_recovery_drill(notify=True)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
