#!/usr/bin/env python3
"""Monitor Pi01 Xmart solar telemetry and send WhatsApp alerts on transitions."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from inneros_core_runtime.notifications.evolution_client import send_whatsapp
from scripts.publish_pi01_xmart_solar_to_ha import infer_mode, read_remote

STATE_FILE = Path(os.getenv("SOLAR_ALERT_STATE_FILE", "/home/rlopez/data/ralfia/solar_xmart_alert_state.json"))
LOW_BATTERY_V = float(os.getenv("SOLAR_ALERT_LOW_BATTERY_V", "24.0"))
CRITICAL_BATTERY_V = float(os.getenv("SOLAR_ALERT_CRITICAL_BATTERY_V", "22.4"))
LOW_BATTERY_SOC = int(os.getenv("SOLAR_ALERT_LOW_BATTERY_SOC", "30"))
CRITICAL_BATTERY_SOC = int(os.getenv("SOLAR_ALERT_CRITICAL_BATTERY_SOC", "15"))
HOT_TEMP_C = int(os.getenv("SOLAR_ALERT_HOT_TEMP_C", "60"))
DEFAULT_COOLDOWN_SECONDS = int(os.getenv("SOLAR_ALERT_COOLDOWN_SECONDS", "1800"))
CRITICAL_COOLDOWN_SECONDS = int(os.getenv("SOLAR_ALERT_CRITICAL_COOLDOWN_SECONDS", "600"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {"state_read_error": True}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_FILE)


def seconds_since(ts: str | None, now: datetime) -> float:
    if not ts:
        return 10**12
    try:
        return (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()
    except Exception:
        return 10**12


def should_send(event: str, state: dict[str, Any], now: datetime, cooldown: int) -> bool:
    last_sent = (state.get("last_sent") or {}).get(event)
    return seconds_since(last_sent, now) >= cooldown


def telemetry_line(telemetry: dict[str, Any]) -> str:
    return (
        f"grid={telemetry.get('grid_voltage_v')}V, "
        f"out={telemetry.get('ac_output_voltage_v')}V/{telemetry.get('ac_output_active_power_w')}W, "
        f"load={telemetry.get('output_load_percent')}%, "
        f"battery={telemetry.get('battery_voltage_v')}V/{telemetry.get('battery_capacity_percent')}%, "
        f"pv={telemetry.get('pv_charging_power_w')}W, "
        f"temp={telemetry.get('inverter_heat_sink_temperature_c')}C"
    )


def build_events(data: dict[str, Any], state: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    if not data.get("ok"):
        return [{
            "event": "reader_error",
            "severity": "warning",
            "message": f"InnerOS Solar: no pude leer el inversor Xmart Pi01. Error={data.get('error') or 'unknown'}",
            "cooldown": DEFAULT_COOLDOWN_SECONDS,
        }]

    telemetry = data.get("telemetry") or {}
    inferred = infer_mode(telemetry)
    last = state.get("last_conditions") or {}
    events: list[dict[str, Any]] = []
    line = telemetry_line(telemetry)

    first_run = not bool(last)
    grid_present = bool(inferred["grid_present"])
    battery_mode = bool(inferred["battery_mode"])
    battery_v = float(telemetry.get("battery_voltage_v") or 0)
    battery_soc = int(telemetry.get("battery_capacity_percent") or 0)
    temp_c = int(telemetry.get("inverter_heat_sink_temperature_c") or 0)

    if (not grid_present and (not first_run or battery_mode)) or (last.get("grid_present") is True and not grid_present):
        events.append({
            "event": "grid_lost",
            "severity": "critical",
            "message": f"InnerOS Solar: se fue la red electrica. Inversor en modo respaldo/bateria. {line}",
            "cooldown": CRITICAL_COOLDOWN_SECONDS,
        })
    if not first_run and last.get("grid_present") is False and grid_present:
        events.append({
            "event": "grid_restored",
            "severity": "info",
            "message": f"InnerOS Solar: volvio la red electrica. {line}",
            "cooldown": DEFAULT_COOLDOWN_SECONDS,
        })
    if battery_v and (battery_v <= CRITICAL_BATTERY_V or battery_soc <= CRITICAL_BATTERY_SOC):
        events.append({
            "event": "battery_critical",
            "severity": "critical",
            "message": f"InnerOS Solar: bateria critica. {line}",
            "cooldown": CRITICAL_COOLDOWN_SECONDS,
        })
    elif battery_v and (battery_v <= LOW_BATTERY_V or battery_soc <= LOW_BATTERY_SOC):
        events.append({
            "event": "battery_low",
            "severity": "warning",
            "message": f"InnerOS Solar: bateria baja. {line}",
            "cooldown": DEFAULT_COOLDOWN_SECONDS,
        })
    if temp_c >= HOT_TEMP_C:
        events.append({
            "event": "inverter_hot",
            "severity": "warning",
            "message": f"InnerOS Solar: temperatura alta del inversor. {line}",
            "cooldown": DEFAULT_COOLDOWN_SECONDS,
        })
    return events


def update_conditions(data: dict[str, Any], state: dict[str, Any], now: datetime) -> None:
    telemetry = data.get("telemetry") or {}
    inferred = infer_mode(telemetry) if telemetry else {}
    state["last_conditions"] = {
        "grid_present": inferred.get("grid_present"),
        "battery_mode": inferred.get("battery_mode"),
        "mode": inferred.get("mode"),
        "battery_voltage_v": telemetry.get("battery_voltage_v"),
        "battery_capacity_percent": telemetry.get("battery_capacity_percent"),
        "pv_charging_power_w": telemetry.get("pv_charging_power_w"),
        "updated_at": now.isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-summary", action="store_true")
    args = parser.parse_args()

    load_dotenv("/home/rlopez/inneros/inneros_core/platform/.env")
    target = (os.getenv("SOLAR_ALERT_WHATSAPP_TO") or os.getenv("RALFIA_ALERTS_TO") or os.getenv("NOTIFY_WHATSAPP_TO") or "").strip()
    now = utc_now()
    state = load_state()
    data = read_remote()
    events = build_events(data, state, now)
    sent: list[dict[str, Any]] = []
    last_sent = state.setdefault("last_sent", {})

    if args.force_summary and data.get("ok"):
        events.append({
            "event": "manual_summary",
            "severity": "info",
            "message": f"InnerOS Solar: resumen manual. {telemetry_line(data.get('telemetry') or {})}",
            "cooldown": 0,
        })

    for event in events:
        name = str(event["event"])
        cooldown = int(event.get("cooldown") or DEFAULT_COOLDOWN_SECONDS)
        if not should_send(name, state, now, cooldown):
            continue
        result = {"ok": True, "dry_run": True}
        if not args.dry_run:
            if not target:
                result = {"ok": False, "status": "error", "message": "missing_whatsapp_target"}
            else:
                result = send_whatsapp(str(event["message"]), number=target, node="primary")
        if result.get("ok"):
            last_sent[name] = now.isoformat()
        sent.append({"event": name, "severity": event.get("severity"), "result": result})

    update_conditions(data, state, now)
    state["last_run_at"] = now.isoformat()
    state["last_ok"] = bool(data.get("ok"))
    save_state(state)
    print(json.dumps({"ok": True, "data_ok": bool(data.get("ok")), "events": [e["event"] for e in events], "sent": sent, "dry_run": args.dry_run}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
