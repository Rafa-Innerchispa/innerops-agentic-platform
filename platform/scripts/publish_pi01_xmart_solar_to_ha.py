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


def main() -> None:
    data = read_remote()
    telemetry = data.get("telemetry") or {}
    common = {
        "friendly_name": "InnerOS Pi01 Solar Status",
        "device_model": data.get("device_model") or "Xmart XSI-BB-120-3K-24-MPP",
        "protocol": data.get("protocol"),
        "usb_vid_pid": data.get("usb_vid_pid") or "0665:5161",
        "source_node": "InnerOs-Pi01",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "safety": data.get("safety") or "read_only_queries_only",
        "raw_field_count": telemetry.get("field_count"),
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
    print(json.dumps({"ok": all(p.get("ok") for p in posted), "status": status, "posted": len(posted), "telemetry": telemetry}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
