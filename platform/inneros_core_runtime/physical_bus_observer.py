"""Read-only local transports: USB, serial, network NIC, Bluetooth and Tailscale.

This module runs on the LOCAL host. It cannot directly identify devices plugged
into another host, such as the solar inverter on Pi01.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path, size: int = 120) -> str | None:
    try:
        return path.read_text(errors="replace").strip()[:size]
    except (OSError, UnicodeError):
        return None


def local_interfaces(root: str = "/sys/class/net") -> list[dict[str, Any]]:
    result = []
    base = Path(root)
    if not base.is_dir():
        return result
    for dev in sorted(base.iterdir())[:64]:
        if dev.name == "lo":
            continue
        item = {"interface": dev.name, "state": _read(dev / "operstate"),
                "carrier": _read(dev / "carrier"),
                "carrier_changes": _read(dev / "carrier_changes"),
                "speed_mbps": _read(dev / "speed"),
                "wifi": (dev / "wireless").is_dir(),
                "errors": {
                    key: _read(dev / "statistics" / key)
                    for key in ("rx_errors", "tx_errors", "rx_dropped", "tx_dropped")
                }}
        result.append(item)
    return result


def local_usb_devices(root: str = "/sys/bus/usb/devices") -> list[dict[str, Any]]:
    found = []
    base = Path(root)
    if not base.is_dir():
        return found
    for dev in sorted(base.iterdir())[:128]:
        vid, pid = _read(dev / "idVendor"), _read(dev / "idProduct")
        if not vid or not pid:
            continue
        identity = (vid + ":" + pid).lower()
        found.append({
            "bus_id": dev.name, "usb_id": identity,
            "manufacturer": _read(dev / "manufacturer"),
            "product": _read(dev / "product"),
            "status": "PRESENT_ON_LOCAL_BUS",
            "possible_xmart_pi01": identity == "0665:5161",
            "data_stream_verified": False,
        })
    return found


def local_serial_ports(root: str = "/sys/class/tty") -> list[str]:
    base = Path(root)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.name.startswith(("ttyUSB", "ttyACM", "ttyAMA", "ttyS")))[:64]


def local_bluetooth_adapters(root: str = "/sys/class/bluetooth") -> list[str]:
    base = Path(root)
    return sorted(p.name for p in base.iterdir() if p.name.startswith("hci"))[:16] if base.is_dir() else []


def tailscale_status(executable: str = "tailscale") -> dict[str, Any]:
    try:
        proc = subprocess.run([executable, "status", "--json"],
                              capture_output=True, text=True, check=False, timeout=4)
        if proc.returncode != 0:
            return {"ok": False, "error": "tailscale_status_unavailable"}
        state = json.loads(proc.stdout)
        return {"ok": True, "backend_state": state.get("BackendState"),
                "peer_count": len(state.get("Peer") or {}),
                "has_exit_node_status": bool(state.get("ExitNodeStatus")),
                "health_warning_count": len(state.get("Health") or []),
                "source": "tailscale_local_only",
                "phone_client_dns_and_routes_checked": False}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def host_observation() -> dict[str, Any]:
    return {"source": "local_host_bus", "host": socket.gethostname(),
            "observed_at": _now(), "interfaces": local_interfaces(),
            "usb": local_usb_devices(), "serial": local_serial_ports(),
            "bluetooth_adapters": local_bluetooth_adapters(),
            "tailscale": tailscale_status(), "remote_hosts_observed": False,
            "usb_bus_traffic_monitored": False, "rf_spectrum_monitored": False,
            "device_mutations": []}


def gateway_impact(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group effects of a disconnected gateway; do not assert root cause."""
    indexed = {str(d.get("device_id")): d for d in devices if d.get("device_id")}
    groups: dict[str, list[str]] = {}
    for device in devices:
        parent = str(device.get("via_device_id") or "")
        if parent and parent in indexed:
            groups.setdefault(parent, []).append(str(device.get("name") or ""))
    findings = []
    for parent, children in groups.items():
        gateway = indexed[parent]
        state = gateway.get("connectivity_status", "UNKNOWN")
        if state in {"OFFLINE", "STALE", "UNKNOWN"}:
            findings.append({"code": "gateway_dependency_attention",
                             "gateway": gateway.get("name"),
                             "gateway_state": state, "dependent_devices": children,
                             "root_cause_confirmed": False})
    return findings
