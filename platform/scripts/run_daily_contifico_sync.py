#!/usr/bin/env python3
"""Pipeline diario: Contifico incremental → ledger → FAC↔COT → inventario → email."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from raphiia_openai.operational import accounting_ledger

    result = accounting_ledger.daily_contifico_pipeline(incremental_pages=10)
    summary = {
        "ok": result.get("ok"),
        "pipeline": result.get("pipeline"),
        "contifico": result.get("steps", {}).get("contifico_incremental"),
        "ledger": result.get("steps", {}).get("ledger_sync"),
        "fac_cot": result.get("steps", {}).get("fac_cot_links"),
        "inventory": result.get("steps", {}).get("inventory", {}).get("upserted"),
        "status": result.get("steps", {}).get("status"),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
