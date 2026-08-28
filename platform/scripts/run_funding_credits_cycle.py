#!/usr/bin/env python3
"""Ciclo AG-54: poll correo → archive → scan créditos/grants."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai.agents import ag54_funding_credits_agent as ag54


def main() -> int:
    result = ag54.agent_funding_sync_and_scan(
        query="bright data credits grant funding prize winner cloud startup voucher",
        limit=50,
        poll_email=True,
    )
    print(json.dumps({"ok": result.get("ok"), "count": result.get("count"), "opportunities": result.get("opportunities", [])[:5]}, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
