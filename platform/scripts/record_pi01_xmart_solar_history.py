#!/usr/bin/env python3
"""Record Pi01 Xmart solar and breaker telemetry for long-term analysis."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv("/home/rlopez/inneros/inneros_core/platform/.env")

from inneros_core_runtime import homeassistant_client as ha
from scripts.publish_pi01_xmart_solar_to_ha import infer_mode, read_remote

HISTORY_ROOT = Path(os.getenv("SOLAR_HISTORY_ROOT", "/home/rlopez/data/ralfia/solar_xmart_history"))
DB_PATH = Path(os.getenv("SOLAR_HISTORY_DB", str(HISTORY_ROOT / "solar_xmart_history.sqlite3")))
RAW_DIR = Path(os.getenv("SOLAR_HISTORY_RAW_DIR", str(HISTORY_ROOT / "raw_jsonl")))

BREAKER_ENTITIES = {
    "breaker_switch": "switch.breaker_switch",
    "breaker_voltage_v": "sensor.breaker_phase_a_voltage",
    "breaker_current_a": "sensor.breaker_phase_a_current",
    "breaker_power_kw": "sensor.breaker_phase_a_power",
    "breaker_total_energy_kwh": "sensor.breaker_total_energy",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_float(value: Any) -> float | None:
    try:
        if value in (None, "", "unknown", "unavailable"):
            return None
        return float(value)
    except Exception:
        return None


def as_int(value: Any) -> int | None:
    number = as_float(value)
    return int(number) if number is not None else None


def bool01(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in {"on", "true", "1", "yes"}:
        return 1
    if text in {"off", "false", "0", "no"}:
        return 0
    return None


def read_entity_state(entity_id: str) -> dict[str, Any]:
    out = ha._request("GET", f"/api/states/{entity_id}")
    data = out.get("data") or {}
    return {
        "ok": bool(out.get("ok")),
        "entity_id": entity_id,
        "state": data.get("state"),
        "attributes": data.get("attributes") or {},
        "last_updated": data.get("last_updated"),
        "error": out.get("error"),
    }


def read_breaker() -> dict[str, Any]:
    readings = {name: read_entity_state(entity_id) for name, entity_id in BREAKER_ENTITIES.items()}
    return {
        "ok": any(item.get("ok") for item in readings.values()),
        "readings": readings,
        "normalized": {
            "breaker_switch": str(readings["breaker_switch"].get("state") or ""),
            "breaker_voltage_v": as_float(readings["breaker_voltage_v"].get("state")),
            "breaker_current_a": as_float(readings["breaker_current_a"].get("state")),
            "breaker_power_kw": as_float(readings["breaker_power_kw"].get("state")),
            "breaker_total_energy_kwh": as_float(readings["breaker_total_energy_kwh"].get("state")),
        },
    }


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS solar_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL UNIQUE,
            date_utc TEXT NOT NULL,
            ok INTEGER NOT NULL,
            mode TEXT,
            grid_present INTEGER,
            battery_mode INTEGER,
            pv_charging INTEGER,
            battery_discharging INTEGER,
            grid_voltage_v REAL,
            grid_frequency_hz REAL,
            output_voltage_v REAL,
            output_frequency_hz REAL,
            output_apparent_va INTEGER,
            output_active_w INTEGER,
            output_load_percent INTEGER,
            battery_voltage_v REAL,
            battery_capacity_percent INTEGER,
            battery_charging_current_a INTEGER,
            battery_discharge_current_a INTEGER,
            pv_input_voltage_v REAL,
            pv_input_current_a REAL,
            pv_charging_power_w INTEGER,
            inverter_temp_c INTEGER,
            breaker_switch TEXT,
            breaker_switch_on INTEGER,
            breaker_voltage_v REAL,
            breaker_current_a REAL,
            breaker_power_kw REAL,
            breaker_total_energy_kwh REAL,
            raw_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_solar_samples_ts ON solar_samples(ts_utc)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_solar_samples_date ON solar_samples(date_utc)")
    return conn


def build_sample(now: datetime) -> dict[str, Any]:
    inverter = read_remote()
    telemetry = inverter.get("telemetry") or {}
    inferred = infer_mode(telemetry) if telemetry else {}
    breaker = read_breaker()
    normalized = breaker.get("normalized") or {}
    sample = {
        "ts_utc": now.isoformat(),
        "date_utc": now.date().isoformat(),
        "inverter": inverter,
        "telemetry": telemetry,
        "inferred": inferred,
        "breaker": breaker,
        "normalized": {
            "ok": bool(inverter.get("ok")),
            "mode": inferred.get("mode"),
            "grid_present": inferred.get("grid_present"),
            "battery_mode": inferred.get("battery_mode"),
            "pv_charging": inferred.get("pv_charging"),
            "battery_discharging": inferred.get("battery_discharging"),
            "grid_voltage_v": as_float(telemetry.get("grid_voltage_v")),
            "grid_frequency_hz": as_float(telemetry.get("grid_frequency_hz")),
            "output_voltage_v": as_float(telemetry.get("ac_output_voltage_v")),
            "output_frequency_hz": as_float(telemetry.get("ac_output_frequency_hz")),
            "output_apparent_va": as_int(telemetry.get("ac_output_apparent_power_va")),
            "output_active_w": as_int(telemetry.get("ac_output_active_power_w")),
            "output_load_percent": as_int(telemetry.get("output_load_percent")),
            "battery_voltage_v": as_float(telemetry.get("battery_voltage_v")),
            "battery_capacity_percent": as_int(telemetry.get("battery_capacity_percent")),
            "battery_charging_current_a": as_int(telemetry.get("battery_charging_current_a")),
            "battery_discharge_current_a": as_int(telemetry.get("battery_discharge_current_a")),
            "pv_input_voltage_v": as_float(telemetry.get("pv_input_voltage_v")),
            "pv_input_current_a": as_float(telemetry.get("pv_input_current_for_battery_a")),
            "pv_charging_power_w": as_int(telemetry.get("pv_charging_power_w")),
            "inverter_temp_c": as_int(telemetry.get("inverter_heat_sink_temperature_c")),
            **normalized,
            "breaker_switch_on": bool01(normalized.get("breaker_switch")),
        },
    }
    return sample


def append_raw_jsonl(sample: dict[str, Any]) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{sample['date_utc']}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def insert_sample(conn: sqlite3.Connection, sample: dict[str, Any]) -> dict[str, Any]:
    n = sample["normalized"]
    raw = json.dumps(sample, ensure_ascii=False, sort_keys=True)
    values = {
        "ts_utc": sample["ts_utc"],
        "date_utc": sample["date_utc"],
        "ok": 1 if n.get("ok") else 0,
        "mode": n.get("mode"),
        "grid_present": bool01(n.get("grid_present")),
        "battery_mode": bool01(n.get("battery_mode")),
        "pv_charging": bool01(n.get("pv_charging")),
        "battery_discharging": bool01(n.get("battery_discharging")),
        "grid_voltage_v": n.get("grid_voltage_v"),
        "grid_frequency_hz": n.get("grid_frequency_hz"),
        "output_voltage_v": n.get("output_voltage_v"),
        "output_frequency_hz": n.get("output_frequency_hz"),
        "output_apparent_va": n.get("output_apparent_va"),
        "output_active_w": n.get("output_active_w"),
        "output_load_percent": n.get("output_load_percent"),
        "battery_voltage_v": n.get("battery_voltage_v"),
        "battery_capacity_percent": n.get("battery_capacity_percent"),
        "battery_charging_current_a": n.get("battery_charging_current_a"),
        "battery_discharge_current_a": n.get("battery_discharge_current_a"),
        "pv_input_voltage_v": n.get("pv_input_voltage_v"),
        "pv_input_current_a": n.get("pv_input_current_a"),
        "pv_charging_power_w": n.get("pv_charging_power_w"),
        "inverter_temp_c": n.get("inverter_temp_c"),
        "breaker_switch": n.get("breaker_switch"),
        "breaker_switch_on": n.get("breaker_switch_on"),
        "breaker_voltage_v": n.get("breaker_voltage_v"),
        "breaker_current_a": n.get("breaker_current_a"),
        "breaker_power_kw": n.get("breaker_power_kw"),
        "breaker_total_energy_kwh": n.get("breaker_total_energy_kwh"),
        "raw_json": raw,
    }
    cols = list(values.keys())
    placeholders = ", ".join(":" + col for col in cols)
    conn.execute(
        f"INSERT OR IGNORE INTO solar_samples ({', '.join(cols)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    row = conn.execute("SELECT COUNT(*) FROM solar_samples").fetchone()
    return {"inserted": conn.total_changes > 0, "total_samples": int(row[0] if row else 0)}


def publish_status(sample: dict[str, Any], total_samples: int) -> None:
    attrs = {
        "friendly_name": "InnerOS Pi01 Solar History Samples",
        "updated_at": sample["ts_utc"],
        "db_path": str(DB_PATH),
        "raw_dir": str(RAW_DIR),
        "mode": sample["normalized"].get("mode"),
        "source": "record_pi01_xmart_solar_history.py",
    }
    ha._request("POST", "/api/states/sensor.inneros_pi01_solar_history_samples", json_body={"state": str(total_samples), "attributes": attrs})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-jsonl", action="store_true")
    parser.add_argument("--no-ha-status", action="store_true")
    args = parser.parse_args()

    load_dotenv("/home/rlopez/inneros/inneros_core/platform/.env")
    now = utc_now()
    sample = build_sample(now)
    conn = connect_db()
    try:
        insert_result = insert_sample(conn, sample)
    finally:
        conn.close()
    raw_path = None
    if not args.no_jsonl:
        raw_path = append_raw_jsonl(sample)
    if not args.no_ha_status:
        publish_status(sample, insert_result["total_samples"])

    out = {
        "ok": True,
        "sample_ok": sample["normalized"].get("ok"),
        "ts_utc": sample["ts_utc"],
        "mode": sample["normalized"].get("mode"),
        "output_active_w": sample["normalized"].get("output_active_w"),
        "pv_charging_power_w": sample["normalized"].get("pv_charging_power_w"),
        "breaker_power_kw": sample["normalized"].get("breaker_power_kw"),
        "battery_capacity_percent": sample["normalized"].get("battery_capacity_percent"),
        "db_path": str(DB_PATH),
        "raw_jsonl": str(raw_path) if raw_path else None,
        **insert_result,
    }
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
