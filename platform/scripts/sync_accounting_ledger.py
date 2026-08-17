#!/usr/bin/env python3
"""Sync contabilidad: Contifico → ledger unificado + capturas email."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from raphiia_openai.operational import accounting_ledger

    result = accounting_ledger.full_accounting_sync(contifico_limit=500)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
