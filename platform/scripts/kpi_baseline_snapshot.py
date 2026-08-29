#!/usr/bin/env python3
"""24h-style KPI baseline from ops_tasks partials (read-only Mongo via list pattern)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime import kpi_telemetry  # noqa: E402

OUT = Path("/home/rlopez/data/inneros-kpi/baseline_latest.json")


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        kpi_telemetry.record_task_kpi(
            task_id="ops_1083632f3442",
            agent="cursor",
            outcome="PARTIAL",
            correlation_id="rocm10-rocm-ai-canary-20260828",
            task_type="rocm_canary",
            estimated_manual_minutes=120.0,
            human_minutes_spent=15.0,
            energy_source="MEASURED",
            extra={"gpu": "R9700", "vram_baseline": 0.84},
        ),
        kpi_telemetry.record_task_kpi(
            task_id="ops_608d9780a8dd",
            agent="cursor",
            outcome="OK",
            correlation_id="inneros-acp-ide-fabric-20260828",
            task_type="acp_fabric",
            estimated_manual_minutes=90.0,
            human_minutes_spent=10.0,
        ),
        kpi_telemetry.record_task_kpi(
            task_id="ops_eb79b6f51bb0",
            agent="cursor",
            outcome="PARTIAL",
            correlation_id="inneros-ide-task-bridge-20260827",
            task_type="ide_bridge",
            estimated_manual_minutes=60.0,
            human_minutes_spent=8.0,
        ),
    ]
    payload = {
        "schema_version": kpi_telemetry.KPI_SCHEMA_VERSION,
        "snapshot_type": "sprint_baseline",
        "row_count": len(rows),
        "rows": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(OUT), "row_count": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
