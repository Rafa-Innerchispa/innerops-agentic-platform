"""Read-only energy history and incident forensics for InnerOS."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlencode

from zoneinfo import ZoneInfo

from raphiia_openai import homeassistant_client as ha

DB_PATH = Path(
    os.getenv(
        "SOLAR_HISTORY_DB",
        "/home/rlopez/data/ralfia/solar_xmart_history/solar_xmart_history.sqlite3",
    )
)

DEFAULT_HA_ENTITIES = [
    "sensor.cuarto_uptime",
    "sensor.breaker_phase_a_current",
    "sensor.breaker_phase_a_power",
    "sensor.breaker_phase_a_voltage",
    "sensor.breaker_total_energy",
    "switch.breaker_switch",
    "sensor.inneros_pi01_solar_output_power",
    "sensor.inneros_pi01_solar_load",
    "sensor.inneros_pi01_solar_grid_voltage",
    "sensor.inneros_pi01_solar_battery_voltage",
    "sensor.inneros_pi01_solar_mode",
]

HISTORY_COLUMNS = [
    "ts_utc",
    "mode",
    "grid_present",
    "battery_mode",
    "grid_voltage_v",
    "output_voltage_v",
    "output_active_w",
    "output_load_percent",
    "battery_voltage_v",
    "battery_capacity_percent",
    "battery_charging_current_a",
    "battery_discharge_current_a",
    "pv_charging_power_w",
    "inverter_temp_c",
    "breaker_switch",
    "breaker_voltage_v",
    "breaker_current_a",
    "breaker_power_kw",
    "breaker_total_energy_kwh",
]


def _parse_dt(value: str, timezone_name: str = "America/Guayaquil") -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError("timestamp_required")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "unknown", "unavailable"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _db_rows(start_utc: datetime, end_utc: datetime, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not DB_PATH.exists():
        return [], {"exists": False, "path": str(DB_PATH)}

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        available = conn.execute(
            "SELECT MIN(ts_utc) AS first_ts_utc, MAX(ts_utc) AS last_ts_utc, COUNT(*) AS total_samples FROM solar_samples"
        ).fetchone()
        cols = ", ".join(HISTORY_COLUMNS)
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT {cols} FROM solar_samples WHERE ts_utc >= ? AND ts_utc <= ? ORDER BY ts_utc ASC LIMIT ?",
                (_iso(start_utc), _iso(end_utc), max(1, min(int(limit), 10000))),
            )
        ]
    finally:
        conn.close()

    meta = {
        "exists": True,
        "path": str(DB_PATH),
        "first_ts_utc": available["first_ts_utc"] if available else None,
        "last_ts_utc": available["last_ts_utc"] if available else None,
        "total_samples": int(available["total_samples"] or 0) if available else 0,
    }
    return rows, meta


def _ha_history(start_utc: datetime, end_utc: datetime, entities: list[str]) -> dict[str, Any]:
    entity_ids = [str(item).strip() for item in entities if str(item).strip()][:32]
    if not entity_ids:
        return {"ok": False, "error": "entities_required", "series": []}

    params = urlencode(
        {
            "filter_entity_id": ",".join(entity_ids),
            "end_time": _iso(end_utc),
            "minimal_response": "1",
            "no_attributes": "1",
        }
    )
    path = f"/api/history/period/{_iso(start_utc)}?{params}"
    raw = ha._request("GET", path, timeout=30.0)
    if not raw.get("ok"):
        return {"ok": False, "error": raw.get("error"), "detail": raw.get("detail"), "series": []}

    flattened: list[dict[str, Any]] = []
    for series in raw.get("data") or []:
        current_entity = None
        for item in series or []:
            current_entity = item.get("entity_id") or current_entity
            flattened.append(
                {
                    "entity_id": current_entity,
                    "state": item.get("state"),
                    "last_changed": item.get("last_changed") or item.get("last_updated"),
                }
            )
    return {
        "ok": True,
        "entities": entity_ids,
        "series": flattened,
        "count": len(flattened),
    }


def solar_history_query(
    start: str,
    end: str,
    limit: int = 2000,
    timezone_name: str = "America/Guayaquil",
    include_ha: bool = True,
) -> dict[str, Any]:
    """Query inverter/breaker history without mutating Home Assistant or hardware."""
    try:
        start_utc = _parse_dt(start, timezone_name)
        end_utc = _parse_dt(end, timezone_name)
    except Exception as exc:
        return {"ok": False, "error": "invalid_timestamp", "detail": str(exc)}

    if end_utc < start_utc:
        return {"ok": False, "error": "end_before_start"}

    rows, db_meta = _db_rows(start_utc, end_utc, limit)
    ha_history = (
        _ha_history(start_utc, end_utc, DEFAULT_HA_ENTITIES)
        if include_ha
        else {"ok": True, "skipped": True, "series": []}
    )
    return {
        "ok": True,
        "read_only": True,
        "start_utc": _iso(start_utc),
        "end_utc": _iso(end_utc),
        "timezone_name": timezone_name,
        "db": db_meta,
        "samples": rows,
        "sample_count": len(rows),
        "ha_history": ha_history,
    }


def _numeric_stats(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [(row.get("ts_utc"), _to_float(row.get(field))) for row in rows]
    clean = [(ts, value) for ts, value in values if value is not None]
    if not clean:
        return {"count": 0, "min": None, "max": None, "avg": None, "first": None, "last": None}
    nums = [value for _, value in clean]
    return {
        "count": len(clean),
        "min": min(nums),
        "max": max(nums),
        "avg": round(mean(nums), 3),
        "first": {"ts_utc": clean[0][0], "value": clean[0][1]},
        "last": {"ts_utc": clean[-1][0], "value": clean[-1][1]},
    }


def _ha_numeric_stats(series: list[dict[str, Any]], entity_id: str, event_utc: datetime) -> dict[str, Any]:
    selected = []
    for item in series:
        if item.get("entity_id") != entity_id:
            continue
        value = _to_float(item.get("state"))
        ts_text = item.get("last_changed")
        if value is None or not ts_text:
            continue
        try:
            ts = _parse_dt(ts_text, "UTC")
        except Exception:
            continue
        selected.append((ts, value))
    selected.sort(key=lambda pair: pair[0])
    if not selected:
        return {"count": 0}

    before = [(ts, value) for ts, value in selected if ts <= event_utc]
    after = [(ts, value) for ts, value in selected if ts > event_utc]
    nums = [value for _, value in selected]
    return {
        "count": len(selected),
        "min": min(nums),
        "max": max(nums),
        "avg": round(mean(nums), 3),
        "last_before": {"ts_utc": _iso(before[-1][0]), "value": before[-1][1]} if before else None,
        "first_after": {"ts_utc": _iso(after[0][0]), "value": after[0][1]} if after else None,
    }


def _closest_uptime(series: list[dict[str, Any]], event_utc: datetime) -> dict[str, Any] | None:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for item in series:
        if item.get("entity_id") != "sensor.cuarto_uptime":
            continue
        state = item.get("state")
        try:
            started = _parse_dt(str(state), "UTC")
        except Exception:
            continue
        candidates.append(
            (
                abs((started - event_utc).total_seconds()),
                {"reported_state": state, "started_at_utc": _iso(started)},
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


def energy_incident_analyze(
    timestamp: str,
    window_minutes: int = 30,
    timezone_name: str = "America/Guayaquil",
) -> dict[str, Any]:
    """Correlate electrical and network evidence around one incident. Never asserts causality."""
    try:
        event_utc = _parse_dt(timestamp, timezone_name)
    except Exception as exc:
        return {"ok": False, "error": "invalid_timestamp", "detail": str(exc)}

    window = max(5, min(int(window_minutes), 240))
    start_utc = event_utc - timedelta(minutes=window)
    end_utc = event_utc + timedelta(minutes=window)
    history = solar_history_query(
        _iso(start_utc),
        _iso(end_utc),
        limit=10000,
        timezone_name="UTC",
        include_ha=True,
    )
    rows = history.get("samples") or []
    before = [row for row in rows if _parse_dt(str(row["ts_utc"]), "UTC") <= event_utc]
    after = [row for row in rows if _parse_dt(str(row["ts_utc"]), "UTC") > event_utc]
    ha_series = (history.get("ha_history") or {}).get("series") or []

    fields = [
        "output_active_w",
        "output_load_percent",
        "grid_voltage_v",
        "breaker_current_a",
        "breaker_power_kw",
        "breaker_voltage_v",
        "battery_voltage_v",
    ]
    db_stats = {
        field: {
            "before": _numeric_stats(before, field),
            "after": _numeric_stats(after, field),
        }
        for field in fields
    }
    ha_stats = {
        "breaker_current_a": _ha_numeric_stats(ha_series, "sensor.breaker_phase_a_current", event_utc),
        "breaker_power_kw": _ha_numeric_stats(ha_series, "sensor.breaker_phase_a_power", event_utc),
        "breaker_voltage_v": _ha_numeric_stats(ha_series, "sensor.breaker_phase_a_voltage", event_utc),
    }

    first_after = rows[len(before)]["ts_utc"] if len(rows) > len(before) else None
    last_before = before[-1]["ts_utc"] if before else None
    uptime = _closest_uptime(ha_series, event_utc)

    observations: list[dict[str, Any]] = []
    if uptime:
        observations.append({"type": "cuarto_restart_evidence", **uptime})
    if not before:
        observations.append(
            {
                "type": "telemetry_gap_before_event",
                "detail": "The local solar history database has no samples in the requested pre-event window.",
            }
        )
    if first_after and not last_before:
        observations.append(
            {
                "type": "telemetry_resumed_after_event",
                "first_sample_after_utc": first_after,
            }
        )

    power_before = ha_stats["breaker_power_kw"]
    current_before = ha_stats["breaker_current_a"]
    if power_before.get("count"):
        observations.append(
            {
                "type": "upstream_power_evidence",
                "max_breaker_power_kw_in_window": power_before.get("max"),
                "last_breaker_power_before_event": power_before.get("last_before"),
            }
        )
    if current_before.get("count"):
        observations.append(
            {
                "type": "upstream_current_evidence",
                "max_breaker_current_a_in_window": current_before.get("max"),
                "last_breaker_current_before_event": current_before.get("last_before"),
            }
        )

    return {
        "ok": True,
        "read_only": True,
        "causality": "not_proven",
        "event": {
            "input": timestamp,
            "event_utc": _iso(event_utc),
            "timezone_name": timezone_name,
            "window_minutes": window,
        },
        "source_status": {
            "solar_db": history.get("db"),
            "solar_sample_count": len(rows),
            "ha_history_ok": bool((history.get("ha_history") or {}).get("ok")),
            "ha_history_count": int((history.get("ha_history") or {}).get("count") or 0),
        },
        "cuarto_uptime": uptime,
        "last_solar_sample_before_event_utc": last_before,
        "first_solar_sample_after_event_utc": first_after,
        "db_stats": db_stats,
        "ha_stats": ha_stats,
        "observations": observations,
        "interpretation_rule": (
            "Evidence may show timing and correlation. Overload is not declared unless the downstream "
            "room-breaker rating and direct downstream current are available."
        ),
    }
