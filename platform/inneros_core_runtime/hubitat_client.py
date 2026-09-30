"""Cliente Hubitat Maker API — sensores Zigbee/Z-Wave vía hub local (sin cloud)."""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", override=True)

HUBITAT_URL = os.getenv("HUBITAT_URL", "http://192.168.1.187").rstrip("/")
HUBITAT_APP_ID = os.getenv("HUBITAT_MAKER_APP_ID", os.getenv("HUBITAT_APP_ID", "")).strip()
HUBITAT_TOKEN = os.getenv("HUBITAT_MAKER_TOKEN", os.getenv("HUBITAT_TOKEN", "")).strip()
HUBITAT_MAC = os.getenv("HUBITAT_MAC", "34:e1:d1:80:6f:00").strip().lower()
HUBITAT_NAME = os.getenv("HUBITAT_NAME", "Timmy").strip()
HUBITAT_SITE = os.getenv("HUBITAT_SITE", "Hubitat").strip()
HUBITAT_STATE_FILE = Path(os.getenv("HUBITAT_STATE_FILE", "/home/rlopez/data/ralfia/hubitat_state.json"))
DEFAULT_DEVICE_LABELS: dict[str, str] = {
    "2": "contacto magnético cuarto",
    "4": "detector movimiento sala",
}


def device_labels() -> dict[str, str]:
    raw = os.getenv("HUBITAT_DEVICE_LABELS", "").strip()
    labels = dict(DEFAULT_DEVICE_LABELS)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                labels.update({str(k): str(v) for k, v in parsed.items()})
        except json.JSONDecodeError:
            pass
    return labels


def display_name(device_id: str, device: dict[str, Any] | None = None) -> str:
    did = str(device_id or "").strip()
    labels = device_labels()
    if did in labels:
        return labels[did]
    if device:
        return str(device.get("label") or device.get("name") or did)
    got = get_device(did)
    if got.get("ok"):
        dev = got.get("device") or {}
        return str(dev.get("label") or dev.get("name") or did)
    return did


def motion_alert_message(device_id: str, *, hub_name: str | None = None) -> str:
    sensor = display_name(device_id)
    hub = (hub_name or HUBITAT_NAME or "Hubitat").strip()
    return f"Hemos detectado movimiento: {sensor} (Hubitat {hub})."


def configured() -> bool:
    return bool(HUBITAT_URL and HUBITAT_APP_ID and HUBITAT_TOKEN)


def _api_path(suffix: str) -> str:
    suffix = suffix.lstrip("/")
    return f"/apps/api/{HUBITAT_APP_ID}/{suffix}"


def _request(method: str, path: str, *, json_body: dict | None = None, timeout: float = 20.0) -> dict[str, Any]:
    if not configured():
        return {
            "ok": False,
            "error": "hubitat_not_configured",
            "hint": "Instala Maker API en el hub y exporta HUBITAT_MAKER_APP_ID + HUBITAT_MAKER_TOKEN en .env",
            "setup": "bash ~/projects/raphiia-openai/scripts/setup_hubitat_maker_api.sh",
            "url": HUBITAT_URL,
            "site": HUBITAT_SITE,
            "hub_name": HUBITAT_NAME,
        }
    url = f"{HUBITAT_URL}{path}"
    params = {"access_token": HUBITAT_TOKEN}
    try:
        r = httpx.request(method, url, params=params, json=json_body, timeout=timeout)
        if r.status_code == 401:
            return {"ok": False, "error": "hubitat_unauthorized", "http_status": 401}
        if not r.is_success:
            return {"ok": False, "error": "hubitat_http_error", "http_status": r.status_code, "body": r.text[:300]}
        if not r.content:
            return {"ok": True}
        body = r.json()
        return {"ok": True, "data": body}
    except Exception as exc:
        return {"ok": False, "error": "hubitat_unreachable", "detail": str(exc)[:200], "url": HUBITAT_URL}


def discover(*, timeout: float = 2.0) -> dict[str, Any]:
    """Comprueba reachability del hub sin token Maker API."""
    host = HUBITAT_URL.removeprefix("http://").removeprefix("https://").split(":")[0]
    maker_open = False
    web_ok = False
    try:
        with socket.create_connection((host, 39501), timeout=timeout):
            maker_open = True
    except OSError:
        maker_open = False
    try:
        r = httpx.get(f"{HUBITAT_URL}/", timeout=timeout)
        web_ok = r.is_success
    except Exception:
        web_ok = False
    return {
        "ok": web_ok or maker_open,
        "url": HUBITAT_URL,
        "host": host,
        "mac_expected": HUBITAT_MAC,
        "hub_name": HUBITAT_NAME,
        "site": HUBITAT_SITE,
        "maker_api_port_open": maker_open,
        "web_ui_reachable": web_ok,
        "configured": configured(),
    }


def ping() -> dict[str, Any]:
    base = discover()
    if not configured():
        base["maker_api"] = {"ok": False, "error": "hubitat_not_configured"}
        return base
    raw = _request("GET", _api_path("devices"))
    if raw.get("ok"):
        devices = raw.get("data") or []
        base["maker_api"] = {"ok": True, "device_count": len(devices) if isinstance(devices, list) else None}
    else:
        base["maker_api"] = raw
    return base


def list_devices(*, limit: int = 200) -> dict[str, Any]:
    raw = _request("GET", _api_path("devices"))
    if not raw.get("ok"):
        return raw
    devices = raw.get("data") or []
    if not isinstance(devices, list):
        return {"ok": False, "error": "hubitat_invalid_devices_payload"}
    slim = []
    for device in devices[: max(1, min(limit, 500))]:
        attrs = device.get("attributes") or {}
        slim.append(
            {
                "id": device.get("id"),
                "name": device.get("name"),
                "label": device.get("label"),
                "type": device.get("type"),
                "room": device.get("room"),
                "model": attrs.get("model") or device.get("model"),
                "manufacturer": attrs.get("manufacturer") or device.get("manufacturer"),
                "capabilities": device.get("capabilities") or [],
            }
        )
    return {"ok": True, "count": len(slim), "devices": slim, "hub": {"url": HUBITAT_URL, "name": HUBITAT_NAME, "site": HUBITAT_SITE}}


def parse_attributes(device: dict[str, Any] | None) -> dict[str, Any]:
    """Normaliza attributes Hubitat (list o dict) a {name: currentValue}."""
    raw = (device or {}).get("attributes") or {}
    out: dict[str, Any] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict) and "currentValue" in value:
                out[key] = value.get("currentValue")
            else:
                out[key] = value
        return out
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("name") is not None:
                out[str(item["name"])] = item.get("currentValue")
    return out


def get_device(device_id: str) -> dict[str, Any]:
    did = (device_id or "").strip()
    if not did:
        return {"ok": False, "error": "device_id_required"}
    raw = _request("GET", _api_path(f"devices/{did}"))
    if not raw.get("ok"):
        return raw
    device = raw.get("data") or {}
    return {"ok": True, "device": device, "attributes": parse_attributes(device)}


def get_attribute(device_id: str, attribute: str) -> dict[str, Any]:
    got = get_device(device_id)
    if not got.get("ok"):
        return got
    name = (attribute or "").strip()
    attrs = got.get("attributes") or {}
    if name not in attrs:
        return {"ok": False, "error": "attribute_not_found", "device_id": device_id, "attribute": name, "available": sorted(attrs.keys())}
    return {"ok": True, "device_id": device_id, "attribute": name, "value": attrs.get(name), "label": (got.get("device") or {}).get("label")}


def refresh_device(device_id: str) -> dict[str, Any]:
    return send_command(device_id, "refresh", capability="Refresh")


def find_device(query: str, *, limit: int = 20) -> dict[str, Any]:
    q = (query or "").strip().lower()
    if not q:
        return {"ok": False, "error": "query_required"}
    listed = list_devices(limit=500)
    if not listed.get("ok"):
        return listed
    matches = []
    for device in listed.get("devices") or []:
        hay = json.dumps(device, ensure_ascii=False).lower()
        if q in hay:
            matches.append(device)
    return {"ok": True, "query": query, "count": len(matches[:limit]), "matches": matches[:limit]}


def send_command(device_id: str, command: str, *, capability: str = "Switch") -> dict[str, Any]:
    did = (device_id or "").strip()
    cmd = (command or "").strip()
    cap = (capability or "Switch").strip()
    if not did or not cmd:
        return {"ok": False, "error": "device_id_and_command_required"}
    raw = _request("GET", _api_path(f"devices/{did}/{cmd}/{cap}"))
    if not raw.get("ok"):
        return raw
    return {"ok": True, "device_id": did, "command": cmd, "capability": cap}


def list_modes() -> dict[str, Any]:
    raw = _request("GET", _api_path("modes"))
    if not raw.get("ok"):
        return raw
    return {"ok": True, "modes": raw.get("data")}


def set_mode(mode_id: str | int) -> dict[str, Any]:
    mid = str(mode_id or "").strip()
    if not mid:
        return {"ok": False, "error": "mode_id_required"}
    raw = _request("GET", _api_path(f"modes/set/{mid}"))
    if not raw.get("ok"):
        return raw
    return {"ok": True, "mode_id": mid}


def list_rooms() -> dict[str, Any]:
    raw = _request("GET", _api_path("rooms"))
    if not raw.get("ok"):
        return raw
    return {"ok": True, "rooms": raw.get("data")}


def get_device_events(device_id: str, *, limit: int = 20) -> dict[str, Any]:
    did = (device_id or "").strip()
    if not did:
        return {"ok": False, "error": "device_id_required"}
    raw = _request("GET", _api_path(f"devices/{did}/events"))
    if not raw.get("ok"):
        return raw
    events = raw.get("data") or []
    if isinstance(events, list):
        events = events[: max(1, min(limit, 200))]
    return {"ok": True, "device_id": did, "events": events}


def capabilities_summary() -> dict[str, Any]:
    """Mapa de lo que InnerOS puede hacer hoy con este hub."""
    listed = list_devices(limit=200)
    modes = list_modes()
    rooms = list_rooms()
    rows = []
    if listed.get("ok"):
        for slim in listed.get("devices") or []:
            full = get_device(str(slim.get("id")))
            dev = full.get("device") or {}
            attrs = full.get("attributes") or {}
            rows.append(
                {
                    "id": slim.get("id"),
                    "label": display_name(str(slim.get("id")), dev),
                    "type": dev.get("type") or slim.get("type"),
                    "attributes": attrs,
                    "commands": dev.get("commands") or [],
                }
            )
    return {
        "ok": True,
        "hub_url": HUBITAT_URL,
        "hub_name": HUBITAT_NAME,
        "integrations": [
            "Maker API (lectura sensores + comandos)",
            "Modos hub (Day/Evening/Night/Away)",
            "Rooms (Disco con Color Arcade)",
            "InnerOS → WhatsApp alertas movimiento",
            "Home Assistant (pendiente integración UI)",
        ],
        "devices": rows,
        "modes": modes.get("modes") if modes.get("ok") else [],
        "rooms": rooms.get("rooms") if rooms.get("ok") else [],
        "cannot_do_via_api": [
            "Emparejar teléfono nuevo sin app Hubitat en el móvil (1 login requerido)",
            "Emparejar Zigbee/Z-Wave nuevos sin botón en el hub",
        ],
    }


def hub_status(*, limit: int = 40) -> dict[str, Any]:
    """Resumen operativo del hub Hubitat (Timmy/Juvita) para AG-32."""
    discovery = discover()
    if not configured():
        return {
            "ok": discovery.get("ok", False),
            "configured": False,
            "discovery": discovery,
            "summary": (
                f"Hubitat {HUBITAT_NAME} ({HUBITAT_SITE}) detectado en {HUBITAT_URL} "
                f"(MAC {HUBITAT_MAC}). Falta Maker API token en .env."
            ),
        }
    devices = list_devices(limit=limit)
    if not devices.get("ok"):
        return {"ok": False, "configured": True, "discovery": discovery, "error": devices}
    rows = devices.get("devices") or []
    sensors = [d for d in rows if "sensor" in str(d.get("type") or "").lower() or "Sensor" in (d.get("capabilities") or [])]
    switches = [d for d in rows if "Switch" in (d.get("capabilities") or [])]
    lines = [
        f"Hubitat {HUBITAT_NAME} @ {HUBITAT_SITE} — {len(rows)} dispositivos visibles.",
        f"Sensores: {len(sensors)} · Switches: {len(switches)}.",
    ]
    for row in rows[:12]:
        lines.append(f"{row.get('name') or row.get('label')}: {row.get('type')}")
    snapshot_cache(limit=limit)
    return {
        "ok": True,
        "configured": True,
        "url": HUBITAT_URL,
        "hub_name": HUBITAT_NAME,
        "site": HUBITAT_SITE,
        "device_count": len(rows),
        "sensor_count": len(sensors),
        "switch_count": len(switches),
        "summary": "\n".join(lines),
        "devices": rows,
    }


def snapshot_cache(*, limit: int = 120) -> dict[str, Any]:
    devices = list_devices(limit=limit) if configured() else {"ok": False, "devices": []}
    discovery = discover()
    snapshot = {
        "ok": bool(discovery.get("ok")),
        "ts": datetime.now(timezone.utc).isoformat(),
        "url": HUBITAT_URL,
        "hub_name": HUBITAT_NAME,
        "site": HUBITAT_SITE,
        "mac": HUBITAT_MAC,
        "configured": configured(),
        "discovery": discovery,
        "devices": devices.get("devices") or [] if devices.get("ok") else [],
        "errors": [] if devices.get("ok") else [devices],
    }
    try:
        HUBITAT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        HUBITAT_STATE_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return snapshot


def read_cached_snapshot() -> dict[str, Any]:
    if not HUBITAT_STATE_FILE.is_file():
        return {"ok": False, "error": "no_cache"}
    try:
        return {"ok": True, **json.loads(HUBITAT_STATE_FILE.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
