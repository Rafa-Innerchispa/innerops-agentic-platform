#!/usr/bin/env python3
"""Publish InnerOS Pi01 Xmart solar telemetry to Home Assistant."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime import homeassistant_client as ha

SSH_TARGET = "rlopez@192.168.1.97"
SSH_KEY = "/home/rlopez/.ssh/ralfia_peer_ops_ed25519"
REMOTE_READER = "/opt/inneros/solar_xmart_mpp_read.py"
STATE_ROOT = Path(os.getenv("SOLAR_READER_STATE_ROOT", "/home/rlopez/data/ralfia"))
LOCK_FILE = Path(os.getenv("SOLAR_READER_LOCK_FILE", str(STATE_ROOT / "solar_xmart_reader.lock")))
CACHE_FILE = Path(os.getenv("SOLAR_READER_CACHE_FILE", str(STATE_ROOT / "solar_xmart_reader_cache.json")))
CACHE_TTL_SECONDS = int(os.getenv("SOLAR_READER_CACHE_TTL_SECONDS", "50"))
SSH_RETRIES = int(os.getenv("SOLAR_READER_SSH_RETRIES", "3"))


def _state(entity_id: str, state: Any, attrs: dict[str, Any]) -> dict[str, Any]:
    return ha._request("POST", f"/api/states/{entity_id}", json_body={"state": str(state), "attributes": attrs})


def _diagnose_ssh_error(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    stderr = (proc.stderr or "")[-1000:]
    stdout = (proc.stdout or "")[-1000:]
    lower = f"{stderr}\n{stdout}".lower()
    if "permission denied" in lower:
        error = "ssh_auth_failed"
    elif "connection timed out" in lower or "operation timed out" in lower:
        error = "ssh_timeout"
    elif "could not resolve hostname" in lower:
        error = "ssh_dns_failed"
    elif "no such file" in lower and REMOTE_READER in lower:
        error = "remote_reader_missing"
    else:
        error = "ssh_reader_failed"
    return {
        "error": error,
        "returncode": proc.returncode,
        "stderr": stderr,
        "stdout": stdout,
        "ssh_target": SSH_TARGET,
        "remote_reader": REMOTE_READER,
    }


def _read_cache(max_age_seconds: int = CACHE_TTL_SECONDS) -> dict[str, Any] | None:
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        age = time.time() - float(raw.get("_cache_written_epoch") or 0)
        if age <= max_age_seconds:
            data = raw.get("data") or {}
            data.setdefault("source_cache", True)
            data["cache_age_seconds"] = round(age, 3)
            return data
    except Exception:
        return None
    return None


def _write_cache(data: dict[str, Any]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"_cache_written_epoch": time.time(), "data": data}
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(CACHE_FILE)
    except Exception:
        pass


def _ssh_read_once() -> dict[str, Any]:
    cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        SSH_TARGET,
        f"python3 {REMOTE_READER}",
    ]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": "ssh_reader_timeout",
            "ssh_target": SSH_TARGET,
            "remote_reader": REMOTE_READER,
            "stdout": (exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-1000:] if isinstance(exc.stderr, str) else "",
        }
    if proc.returncode != 0:
        return {"ok": False, **_diagnose_ssh_error(proc)}
    try:
        data = json.loads(proc.stdout)
        data.setdefault("ok", True)
        data["source_cache"] = False
        return data
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "invalid_reader_json", "detail": str(exc), "stdout": proc.stdout[-1000:]}


def _with_reader_lock() -> Any:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    return LOCK_FILE.open("a+", encoding="utf-8")


def read_remote() -> dict[str, Any]:
    cached = _read_cache()
    if cached:
        return cached

    with _with_reader_lock() as lock_fh:
        try:
            import fcntl

            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass

        cached = _read_cache()
        if cached:
            return cached

        last_error: dict[str, Any] | None = None
        for attempt in range(1, max(1, SSH_RETRIES) + 1):
            data = _ssh_read_once()
            if data.get("ok"):
                data["reader_attempt"] = attempt
                _write_cache(data)
                return data
            last_error = data
            if attempt < SSH_RETRIES:
                time.sleep(1.0)

        stale = _read_cache(max_age_seconds=3600)
        if last_error is None:
            last_error = {"ok": False, "error": "unknown_reader_failure"}
        last_error["ok"] = False
        last_error["attempts"] = max(1, SSH_RETRIES)
        if stale:
            last_error["last_good"] = {
                "cache_age_seconds": stale.get("cache_age_seconds"),
                "ts": stale.get("ts"),
                "telemetry": stale.get("telemetry"),
            }
        return last_error


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
