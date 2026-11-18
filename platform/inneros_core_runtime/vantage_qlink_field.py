"""Read-only field bridge for legacy Vantage QLink (CLMNES050).

This module is deliberately *not* a QLink programmer or a relay driver.
It captures serial diagnostics on the technician's onsite computer and
permits only a bounded non-mutating VGS# query for a known keypad address.  The existing InnerOS AG-60/HA service can
consume captured JSON only after an authenticated site association.

QLink is NOT InFusion.  Do not substitute the Home Assistant InFusion
integration for this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVIDER_ID = "vantage_qlink"
MODEL = "CLMNES050"
DEFAULT_BAUDRATE = 19200
MAX_LINE_BYTES = 256
MAX_EVENTS = 500
MAX_SECONDS = 60

# Explicitly distinguish a button or enclosure report from station-bus relays.
_BUTTON = re.compile(r"^(SW|RGS#|VGS#)\s+(\d+)\s+(\d+)\s+(\d+)\s+([01])$", re.I)
_ENCLOSURE = re.compile(r"^LO\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)$", re.I)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_line(raw: str | bytes) -> dict[str, Any]:
    """Parse documented observations, never infer a relay's state from a key."""
    if isinstance(raw, bytes):
        line = raw[:MAX_LINE_BYTES].decode("ascii", errors="replace").strip()
    else:
        line = str(raw)[:MAX_LINE_BYTES].strip()
    if not line:
        return {"kind": "empty"}
    match = _BUTTON.fullmatch(line)
    if match:
        prefix, master, station, button, value = match.groups()
        return {
            "kind": "button_event" if prefix.upper() == "SW" else "button_state",
            "master": int(master),
            "station": int(station),
            "button": int(button),
            "value": int(value),
            "source": prefix.upper(),
            "load_state_verified": False,
        }
    match = _ENCLOSURE.fullmatch(line)
    if match:
        master, enclosure, module, load, level = map(int, match.groups())
        return {
            "kind": "enclosure_load_report",
            "master": master,
            "enclosure": enclosure,
            "module": module,
            "load": load,
            "level": level,
            "station_bus_relay": False,
        }
    if line.startswith("LS "):
        # VGC/VLC Station Bus command grammar must be verified before decoding.
        return {"kind": "station_load_unverified", "raw": line}
    return {"kind": "unknown", "raw": line}



def query_switch_state(port: str, *, site_id: str, master: int,
                       station: int, button: int, timeout_seconds: float = 3.0,
                       baudrate: int = DEFAULT_BAUDRATE) -> dict[str, Any]:
    """Issue ONLY the known QLink VGS# query for one already-known switch address.

    Read-only at device level, but sends one serial QUERY.  It does not
    discover unknown addresses, control loads, trigger scenes or program QLink.
    The response describes a BUTTON, not the actual physical light/relay.
    Source: https://github.com/imfinlay/vantage-qlink-api (documented VGS#).
    """
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", site_id or ""):
        raise ValueError("site_id_required")
    if not port or not isinstance(port, str):
        raise ValueError("serial_port_required")
    for item, value in (("master", master), ("station", station), ("button", button)):
        if type(value) is not int or not (1 <= value <= 255):
            raise ValueError(f"{item}_must_be_known_positive_address")
    if not (0.1 <= timeout_seconds <= 10):
        raise ValueError("timeout_seconds_out_of_range")
    if baudrate not in {9600, 19200, 38400, 57600, 115200}:
        raise ValueError("unsupported_baudrate")
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyserial_missing") from exc
    request = f"VGS# {master} {station} {button}\r\n".encode("ascii")
    observed: list[dict[str, Any]] = []
    with serial.Serial(port=port, baudrate=baudrate, bytesize=8, parity="N",
                       stopbits=1, timeout=0.25, write_timeout=0.25) as conn:
        conn.write(request)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and len(observed) < 30:
            reply = conn.readline(MAX_LINE_BYTES)
            if not reply:
                continue
            item = parse_line(reply)
            observed.append(item)
            if item.get("kind") != "button_state":
                continue
            if item.get("source") not in {"RGS#", "VGS#"}:
                continue
            if (item.get("master"), item.get("station"), item.get("button")) != (
                master, station, button
            ):
                continue
            return {
                "ok": True, "site_id": site_id, "provider_id": PROVIDER_ID,
                "query": "VGS#", "query_transmitted": 1,
                "mutating_commands_transmitted": 0,
                "master": master, "station": station, "button": button,
                "button_state": item["value"],
                "station_bus_relay_state_verified": False,
                "response": item, "mode": "read_only_query",
            }
    return {
        "ok": False, "error": "qlink_switch_query_timeout",
        "site_id": site_id, "provider_id": PROVIDER_ID,
        "query": "VGS#", "query_transmitted": 1,
        "mutating_commands_transmitted": 0,
        "target": {"master": master, "station": station, "button": button},
        "station_bus_relay_state_verified": False,
        "observed_count": len(observed),
    }

def list_serial_ports() -> dict[str, Any]:
    """Inventory serial ports on the *onsite* host, not AMD/Intel remotely."""
    try:
        from serial.tools import list_ports  # type: ignore
    except ImportError:
        return {"ok": False, "error": "pyserial_missing", "install": "python -m pip install pyserial"}
    rows = [
        {"port": p.device, "description": p.description, "hwid": p.hwid}
        for p in list_ports.comports()
    ]
    return {"ok": True, "host_scope": "local_only", "ports": rows}


def observe_serial(port: str, *, seconds: float = 5.0, baudrate: int = DEFAULT_BAUDRATE,
                   site_id: str, max_events: int = 100) -> dict[str, Any]:
    """Observe unsolicited serial frames; absolutely NO TX or controller writes."""
    if not site_id or len(site_id) > 128 or not re.fullmatch(r"[a-zA-Z0-9_-]+", site_id):
        raise ValueError("site_id_required_and_must_be_slug")
    if not port or not isinstance(port, str):
        raise ValueError("serial_port_required")
    if not (0 < seconds <= MAX_SECONDS):
        raise ValueError("seconds_out_of_range")
    if not (1 <= max_events <= MAX_EVENTS):
        raise ValueError("max_events_out_of_range")
    if baudrate not in {9600, 19200, 38400, 57600, 115200}:
        raise ValueError("unsupported_baudrate")
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyserial_missing") from exc
    events: list[dict[str, Any]] = []
    started = utcnow()
    with serial.Serial(port=port, baudrate=baudrate, bytesize=8, parity="N",
                       stopbits=1, timeout=0.25, write_timeout=0.25) as conn:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and len(events) < max_events:
            line = conn.readline(MAX_LINE_BYTES)
            if not line:
                continue
            record = parse_line(line)
            if record["kind"] != "empty":
                events.append({"observed_at": utcnow(), **record})
    return {
        "ok": True, "provider_id": PROVIDER_ID, "site_id": site_id,
        "controller_model_assumed": MODEL, "model_verified": False,
        "mode": "read_only_passive", "transmitted_commands": 0,
        "host_scope": "onsite_computer", "started_at": started,
        "ended_at": utcnow(), "frames": events, "count": len(events),
        "relay_control_implemented": False, "qlink_programming_implemented": False,
    }


def backup_manifest(paths: list[str], *, site_id: str, allowed_root: str | None = None) -> dict[str, Any]:
    """Hash local QLink backups within an approved folder, without changing them."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", site_id or ""):
        raise ValueError("site_id_required")
    import os
    root = Path(allowed_root or os.getenv("VANTAGE_QLINK_BACKUP_ROOT") or Path.cwd()).resolve()
    if not root.is_dir():
        raise ValueError("backup_root_not_directory")
    items: list[dict[str, Any]] = []
    for name in paths:
        original = Path(name)
        if original.is_symlink():
            raise ValueError("backup_symlink_not_allowed")
        path = original.resolve()
        if not path.is_relative_to(root):
            raise ValueError("backup_outside_approved_root")
        if not path.is_file() or path.suffix.lower() not in {".qlk", ".bak", ".bin"}:
            raise ValueError("unexpected_backup_extension")
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("backup_too_large")
        data = path.read_bytes()
        items.append({
            "name": path.name, "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "parsing_verified": False,
        })
    return {"ok": True, "site_id": site_id, "approved_root": str(root),
            "backups": items, "source_files_modified": False, "source_files_uploaded": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="InnerOS Vantage QLink on-site READ-ONLY bridge")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list-ports", action="store_true")
    group.add_argument("--observe", metavar="SERIAL_PORT")
    group.add_argument("--manifest", nargs="+", metavar="QLINK_BACKUP")
    parser.add_argument("--site", help="InnerOS client site slug (e.g. test_site)")
    parser.add_argument("--seconds", type=float, default=5.0, help="Passive capture duration (max 60s)")
    args = parser.parse_args(argv)
    return _dispatch(parser, args, argv)


def _dispatch(parser: argparse.ArgumentParser, args: Any, argv: list[str] | None) -> int:
    # Extra options are declared by parent parser in the final CLI wrapper.
    if args.list_ports:
        result = list_serial_ports()
    elif args.observe:
        site_id = getattr(args, "site", None)
        if not site_id:
            parser.error("--site is required with --observe")
        result = observe_serial(args.observe, seconds=float(getattr(args, "seconds", 5.0)),
                                site_id=site_id)
    else:
        site_id = getattr(args, "site", None)
        if not site_id:
            parser.error("--site is required with --manifest")
        result = backup_manifest(args.manifest, site_id=site_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
