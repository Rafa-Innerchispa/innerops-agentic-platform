#!/usr/bin/env python3
"""Summarize recorded Pi01 Xmart solar history."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("SOLAR_HISTORY_DB", "/home/rlopez/data/ralfia/solar_xmart_history/solar_xmart_history.sqlite3"))


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def avg(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 3) if clean else None


def estimate_energy(rows: list[dict[str, Any]]) -> dict[str, float]:
    output_kwh = 0.0
    pv_kwh = 0.0
    breaker_kwh_power = 0.0
    for prev, current in zip(rows, rows[1:]):
        dt = (parse_ts(current["ts_utc"]) - parse_ts(prev["ts_utc"])).total_seconds()
        if dt <= 0 or dt > 300:
            continue
        hours = dt / 3600.0
        if prev.get("output_active_w") is not None:
            output_kwh += float(prev["output_active_w"]) / 1000.0 * hours
        if prev.get("pv_charging_power_w") is not None:
            pv_kwh += float(prev["pv_charging_power_w"]) / 1000.0 * hours
        if prev.get("breaker_power_kw") is not None:
            breaker_kwh_power += float(prev["breaker_power_kw"]) * hours
    return {
        "estimated_output_kwh": round(output_kwh, 3),
        "estimated_pv_charge_kwh": round(pv_kwh, 3),
        "estimated_breaker_kwh_from_power": round(breaker_kwh_power, 3),
    }


def summarize(since_hours: int) -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"ok": False, "error": "history_db_missing", "db_path": str(DB_PATH)}
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM solar_samples WHERE ts_utc >= ? ORDER BY ts_utc ASC",
            (since.isoformat(),),
        )]
    finally:
        conn.close()
    if not rows:
        return {"ok": True, "db_path": str(DB_PATH), "since_hours": since_hours, "samples": 0}

    breaker_totals = [row.get("breaker_total_energy_kwh") for row in rows if row.get("breaker_total_energy_kwh") is not None]
    energy = estimate_energy(rows)
    if breaker_totals:
        energy["breaker_total_delta_kwh"] = round(float(max(breaker_totals)) - float(min(breaker_totals)), 3)

    battery_values = [row.get("battery_capacity_percent") for row in rows if row.get("battery_capacity_percent") is not None]
    modes: dict[str, int] = {}
    for row in rows:
        mode = row.get("mode") or "unknown"
        modes[mode] = modes.get(mode, 0) + 1

    return {
        "ok": True,
        "db_path": str(DB_PATH),
        "since_hours": since_hours,
        "samples": len(rows),
        "first_ts_utc": rows[0]["ts_utc"],
        "last_ts_utc": rows[-1]["ts_utc"],
        "mode_counts": modes,
        "avg_output_w": avg([row.get("output_active_w") for row in rows]),
        "max_output_w": max([row.get("output_active_w") or 0 for row in rows]),
        "avg_pv_w": avg([row.get("pv_charging_power_w") for row in rows]),
        "max_pv_w": max([row.get("pv_charging_power_w") or 0 for row in rows]),
        "avg_breaker_kw": avg([row.get("breaker_power_kw") for row in rows]),
        "max_breaker_kw": max([row.get("breaker_power_kw") or 0 for row in rows]),
        "battery_soc_min": min(battery_values) if battery_values else None,
        "battery_soc_max": max(battery_values) if battery_values else None,
        **energy,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-hours", type=int, default=24)
    args = parser.parse_args()
    print(json.dumps(summarize(max(1, args.since_hours)), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
