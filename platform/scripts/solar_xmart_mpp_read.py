#!/usr/bin/env python3
"""Read-only Xmart/MPP Solar PI30 telemetry over USB HID."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import hid

VID = 0x0665
PID = 0x5161

QPIGS_FIELDS = [
    ("grid_voltage_v", float),
    ("grid_frequency_hz", float),
    ("ac_output_voltage_v", float),
    ("ac_output_frequency_hz", float),
    ("ac_output_apparent_power_va", int),
    ("ac_output_active_power_w", int),
    ("output_load_percent", int),
    ("bus_voltage_v", int),
    ("battery_voltage_v", float),
    ("battery_charging_current_a", int),
    ("battery_capacity_percent", int),
    ("inverter_heat_sink_temperature_c", int),
    ("pv_input_current_for_battery_a", float),
    ("pv_input_voltage_v", float),
    ("battery_voltage_from_scc_v", float),
    ("battery_discharge_current_a", int),
    ("device_status", str),
    ("battery_voltage_offset_for_fans_on", str),
    ("eeprom_version", str),
    ("pv_charging_power_w", int),
    ("device_status_2", str),
]


def crc_xmodem(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def command_frame(command: str) -> bytes:
    body = command.encode("ascii")
    crc = crc_xmodem(body)
    return body + bytes([(crc >> 8) & 0xFF, crc & 0xFF]) + b"\r"


def clean_response(data: bytes) -> dict[str, Any]:
    raw = data.split(b"\r", 1)[0]
    if not raw:
        return {"ok": False, "error": "empty_response", "raw_hex": data.hex()}
    if raw.startswith(b"(") and len(raw) >= 3:
        payload = raw[1:-2]
        response_crc = raw[-2:].hex()
    else:
        payload = raw
        response_crc = None
    text = payload.decode("ascii", errors="replace")
    return {"ok": True, "text": text, "response_crc_hex": response_crc, "raw_hex": raw.hex()}


def send_query(command: str, report_len: int = 8) -> dict[str, Any]:
    rows = hid.enumerate(VID, PID)
    if not rows:
        return {"ok": False, "command": command, "error": "device_not_found", "vid_pid": "0665:5161"}
    dev = hid.device()
    dev.open_path(rows[0]["path"])
    dev.set_nonblocking(True)
    try:
        payload = command_frame(command)
        for offset in range(0, len(payload), report_len):
            chunk = payload[offset : offset + report_len]
            dev.write(bytes([0]) + chunk.ljust(report_len, b"\x00"))
            time.sleep(0.08)
        deadline = time.time() + 4.0
        data = bytearray()
        while time.time() < deadline:
            part = dev.read(64, timeout_ms=250)
            if part:
                block = bytes(part)
                data.extend(block)
                if b"\r" in data:
                    break
        cleaned = clean_response(bytes(data))
        cleaned["command"] = command
        return cleaned
    finally:
        dev.close()


def parse_qpigs(text: str) -> dict[str, Any]:
    fields = text.strip().split()
    parsed: dict[str, Any] = {"raw_fields": fields, "field_count": len(fields)}
    for index, (name, caster) in enumerate(QPIGS_FIELDS):
        if index >= len(fields):
            break
        value = fields[index]
        try:
            parsed[name] = caster(value)
        except Exception:
            parsed[name] = value
    return parsed


def main() -> None:
    qpi = send_query("QPI")
    qpigs = send_query("QPIGS")
    telemetry: dict[str, Any] = {}
    if qpigs.get("ok"):
        telemetry = parse_qpigs(str(qpigs.get("text") or ""))
    ok = bool(qpi.get("ok") and qpigs.get("ok") and telemetry)
    print(json.dumps({
        "ok": ok,
        "ts": datetime.now(timezone.utc).isoformat(),
        "device_model": "Xmart XSI-BB-120-3K-24-MPP",
        "protocol": qpi.get("text") if qpi.get("ok") else None,
        "usb_vid_pid": "0665:5161",
        "queries": {"QPI": qpi, "QPIGS": qpigs},
        "telemetry": telemetry,
        "safety": "read_only_queries_only",
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
