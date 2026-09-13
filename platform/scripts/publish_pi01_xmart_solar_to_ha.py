#!/usr/bin/env python3
"""Publish InnerOS Pi01 Xmart solar telemetry to Home Assistant."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any

from inneros_core_runtime import homeassistant_client as ha

SSH_TARGET = "rlopez@192.168.1.97"
SSH_KEY = "/home/rlopez/.ssh/ralfia_peer_ops_ed25519"
REMOTE_READER = "/opt/inneros/solar_xmart_mpp_read.py"


def _state(entity_id: str, state: Any, attrs: dict[str, Any]) -> dict[str, Any]:
    return ha._request("POST", f"/api/states/{entity_id}", json_body={"state": str(state), "attributes": attrs})


def read_remote() -> dict[str, Any]:
    cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        SSH_TARGET,
        f"python3 {REMOTE_READER}",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
    if proc.returncode != 0:
        return {"ok": False, "error": "ssh_reader_failed", "returncode": proc.returncode, "stderr": proc.stderr[-500:]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "invalid_reader_json", "detail": str(exc), "stdout": proc.stdout[-500:]}


def infer_mode(telemetry: dict[str, Any]) -> dict[str, Any]:
    grid_voltage = float(telemetry.get("grid_voltage_v") or 0)
    output_voltage = float(telemetry.get("ac_output_voltage_v") or 0)
    pv_power = int(telemetry.get("pv_charging_power_w") or 0)
    battery_discharge = int(telemetry.get("battery_discharge_current_a") or 0)
    battery_charge = int(telemetry.get("battery_charging_current_a") or 0)
    battery_capacity = int(telemetry.get("battery_capacity_percent") or 0)
    battery_voltage = float(telemetry.get("battery_voltage_v") or 0)

    grid_present = grid_voltage >= 90.0
    output_present = output_voltage >= 90.0
    battery_mode = (not grid_present) and output_present

    if battery_mode:
        mode = "battery_backup"
    elif grid_present and pv_power > 0 and battery_charge > 0:
        mode = "utility_present_solar_charging"
    elif grid_present and battery_capacity >= 95 and battery_voltage >= 28.0:
        mode = "utility_present_backup_float"
    elif grid_present:
        mode = "utility_present"
    elif output_present:
        mode = "inverter_output_no_grid"
    else:
        mode = "offline_or_unknown"

    return {
        "mode": mode,
        "grid_present": grid_present,
        "output_present": output_present,
        "battery_mode": battery_mode,
        "pv_charging": pv_power > 0,
        "battery_discharging": battery_discharge > 0,
    }


def main() -> None:
    data = read_remote()
    telemetry = data.get("telemetry") or {}
    inferred = infer_mode(telemetry)
    common = {
        "friendly_name": "InnerOS Pi01 Solar Status",
        "device_model": data.get("device_model") or "Xmart XSI-BB-120-3K-24-MPP",
        "protocol": data.get("protocol"),
        "usb_vid_pid": data.get("usb_vid_pid") or "0665:5161",
        "source_node": "InnerOs-Pi01",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "safety": data.get("safety") or "read_only_queries_only",
        "raw_field_count": telemetry.get("field_count"),
        "mode_inferred": inferred,
    }
    status = "online" if data.get("ok") else "error"
    posted = [_state("sensor.inneros_pi01_solar_status", status, {**common, "reader": data})]
    sensor_map = {
        "battery_voltage_v": ("sensor.inneros_pi01_solar_battery_voltage", "V", "voltage"),
        "battery_capacity_percent": ("sensor.inneros_pi01_solar_battery_capacity", "%", "battery"),
        "ac_output_active_power_w": ("sensor.inneros_pi01_solar_output_power", "W", "power"),
        "output_load_percent": ("sensor.inneros_pi01_solar_load", "%", None),
        "pv_input_voltage_v": ("sensor.inneros_pi01_solar_pv_voltage", "V", "voltage"),
        "inverter_heat_sink_temperature_c": ("sensor.inneros_pi01_solar_temperature", "°C", "temperature"),
        "grid_voltage_v": ("sensor.inneros_pi01_solar_grid_voltage", "V", "voltage"),
        "ac_output_voltage_v": ("sensor.inneros_pi01_solar_output_voltage", "V", "voltage"),
    }
    for key, (entity, unit, device_class) in sensor_map.items():
        if key not in telemetry:
            continue
        attrs = {**common, "source_field": key, "unit_of_measurement": unit, "state_class": "measurement"}
        if device_class:
            attrs["device_class"] = device_class
        posted.append(_state(entity, telemetry[key], attrs))
    posted.append(_state("sensor.inneros_pi01_solar_mode", inferred["mode"], {**common, "friendly_name": "InnerOS Pi01 Solar Mode"}))
    posted.append(_state(
        "binary_sensor.inneros_pi01_solar_grid_present",
        "on" if inferred["grid_present"] else "off",
        {**common, "friendly_name": "InnerOS Pi01 Grid Present", "device_class": "power"},
    ))
    posted.append(_state(
        "binary_sensor.inneros_pi01_solar_battery_mode",
        "on" if inferred["battery_mode"] else "off",
        {**common, "friendly_name": "InnerOS Pi01 Battery Backup Mode", "device_class": "power"},
    ))
    print(json.dumps({"ok": all(p.get("ok") for p in posted), "status": status, "posted": len(posted), "telemetry": telemetry, "inferred": inferred}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
