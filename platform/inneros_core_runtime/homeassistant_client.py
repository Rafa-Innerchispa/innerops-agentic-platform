"""Cliente Home Assistant REST — domótica local sin créditos cloud."""

from __future__ import annotations

import json
import os
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import websockets
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", override=True)

HA_URL = os.getenv("HOME_ASSISTANT_URL", os.getenv("HA_URL", "http://192.168.1.4:8123")).rstrip("/")
HA_TOKEN = os.getenv("HOME_ASSISTANT_TOKEN", os.getenv("HA_TOKEN", "")).strip()
HA_STATE_FILE = Path(os.getenv("HA_STATE_FILE", "/home/rlopez/data/ralfia/ha_state.json"))

# Alias habitación → fragmentos entity_id / friendly_name (español + nombres HA reales)
ROOM_ALIASES: dict[str, list[str]] = {
    "living": ["cinta_mural", "cinta", "living", "sala"],
    "sala": ["cinta_mural", "cinta", "living", "sala"],
    "cocina": ["luz_cocina", "piedra_cocina", "cocina"],
    "estudio": ["luz_estudio", "cinta_escritorio", "estudio"],
    "bodega": ["luz_bodega", "bodega"],
    "escritorio": ["cinta_escritorio", "luz_estudio", "escritorio"],
    "entrada": ["entrada", "corona"],
    "pecera": ["pecera", "tomacorriente_doble_pecera"],
}


def _headers() -> dict[str, str]:
    if not HA_TOKEN:
        return {}
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


def configured() -> bool:
    return bool(HA_URL and HA_TOKEN)


def _request(method: str, path: str, *, json_body: dict | None = None, timeout: float = 25.0) -> dict[str, Any]:
    if not HA_TOKEN:
        return {
            "ok": False,
            "error": "ha_token_missing",
            "hint": "Crea token en HA → Perfil → Tokens. Export HOME_ASSISTANT_TOKEN en .env",
            "setup": "bash ~/projects/ralfiia-amd-standby/scripts/setup_home_assistant_token.sh",
        }
    url = f"{HA_URL}{path}"
    try:
        r = httpx.request(method, url, headers=_headers(), json=json_body, timeout=timeout)
        if r.status_code == 401:
            return {"ok": False, "error": "ha_unauthorized", "http_status": 401}
        if not r.is_success:
            return {"ok": False, "error": "ha_http_error", "http_status": r.status_code, "body": r.text[:300]}
        if not r.content:
            return {"ok": True}
        body = r.json()
        return {"ok": True, "data": body}
    except Exception as exc:
        return {"ok": False, "error": "ha_unreachable", "detail": str(exc)[:200], "url": HA_URL}


def _ws_url() -> str:
    if HA_URL.startswith("https://"):
        return "wss://" + HA_URL.removeprefix("https://") + "/api/websocket"
    if HA_URL.startswith("http://"):
        return "ws://" + HA_URL.removeprefix("http://") + "/api/websocket"
    return HA_URL.rstrip("/") + "/api/websocket"


async def _ws_call_async(message_type: str, payload: dict[str, Any] | None = None, timeout: float = 20.0) -> dict[str, Any]:
    if not HA_TOKEN:
        return {"ok": False, "error": "ha_token_missing"}
    ws_url = _ws_url()
    try:
        async with websockets.connect(ws_url, open_timeout=timeout, close_timeout=5) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            if hello.get("type") != "auth_required":
                return {"ok": False, "error": "ha_ws_protocol_error", "phase": "hello", "message_type": hello.get("type")}
            await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
            auth = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            if auth.get("type") != "auth_ok":
                return {"ok": False, "error": "ha_ws_auth_failed", "message_type": auth.get("type")}
            request_id = 1
            await ws.send(json.dumps({"id": request_id, "type": message_type, **(payload or {})}))
            while True:
                reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                if reply.get("id") == request_id:
                    if not reply.get("success", False):
                        return {"ok": False, "error": "ha_ws_command_failed", "message_type": message_type, "ha_error": reply.get("error")}
                    return {"ok": True, "data": reply.get("result")}
    except Exception as exc:
        return {"ok": False, "error": "ha_ws_unreachable", "detail": str(exc)[:200], "url": HA_URL}


def ws_call(message_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one Home Assistant WebSocket command; token is kept server-side."""
    return asyncio.run(_ws_call_async(message_type, payload))


def ping() -> dict[str, Any]:
    out = _request("GET", "/api/")
    if out.get("ok"):
        out["configured"] = True
        out["url"] = HA_URL
    return out


def list_states(*, domain: str | None = None, limit: int = 80) -> dict[str, Any]:
    raw = _request("GET", "/api/states")
    if not raw.get("ok"):
        return raw
    states = raw.get("data") or []
    if domain:
        prefix = domain.strip().lower() + "."
        states = [s for s in states if str(s.get("entity_id", "")).startswith(prefix)]
    slim = []
    for s in states[: max(1, min(limit, 500))]:
        slim.append(
            {
                "entity_id": s.get("entity_id"),
                "state": s.get("state"),
                "friendly_name": (s.get("attributes") or {}).get("friendly_name"),
            }
        )
    return {"ok": True, "count": len(slim), "entities": slim, "domain_filter": domain}


def list_entity_registry(*, limit: int = 500, integration: str | None = None) -> dict[str, Any]:
    raw = ws_call("config/entity_registry/list")
    if not raw.get("ok"):
        return raw
    rows = raw.get("data") or []
    if integration:
        needle = integration.strip().lower()
        rows = [r for r in rows if needle in str(r.get("platform") or r.get("config_entry_id") or "").lower()]
    entities = []
    for row in rows[: max(1, min(limit, 2000))]:
        entities.append(
            {
                "entity_id": row.get("entity_id"),
                "original_name": row.get("original_name"),
                "name": row.get("name"),
                "device_id": row.get("device_id"),
                "platform": row.get("platform"),
                "config_entry_id": row.get("config_entry_id"),
                "area_id": row.get("area_id"),
                "disabled_by": row.get("disabled_by"),
            }
        )
    return {"ok": True, "count": len(entities), "entities": entities}


def list_devices(*, limit: int = 500, integration: str | None = None) -> dict[str, Any]:
    raw = ws_call("config/device_registry/list")
    if not raw.get("ok"):
        return raw
    rows = raw.get("data") or []
    if integration:
        needle = integration.strip().lower()
        rows = [
            r
            for r in rows
            if needle in json.dumps(r.get("identifiers") or [], ensure_ascii=False).lower()
            or needle in json.dumps(r.get("connections") or [], ensure_ascii=False).lower()
            or needle in str(r.get("manufacturer") or "").lower()
            or needle in str(r.get("model") or "").lower()
            or needle in str(r.get("name") or "").lower()
        ]
    devices = []
    for row in rows[: max(1, min(limit, 2000))]:
        devices.append(
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "name_by_user": row.get("name_by_user"),
                "manufacturer": row.get("manufacturer"),
                "model": row.get("model"),
                "sw_version": row.get("sw_version"),
                "area_id": row.get("area_id"),
                "config_entries": row.get("config_entries"),
                "connections": row.get("connections"),
                "identifiers": row.get("identifiers"),
            }
        )
    return {"ok": True, "count": len(devices), "devices": devices}


def _registry_lookup(rows: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    needle = (value or "").strip().lower()
    if not needle:
        return None
    if key:
        for row in rows:
            if str(row.get(key) or "").lower() == needle:
                return row
    matches = []
    for row in rows:
        haystack = json.dumps(row, ensure_ascii=False).lower()
        if needle in haystack:
            matches.append(row)
    return matches[0] if len(matches) == 1 else None


def ha_rename_entity_name(entity_id: str, name: str, *, dry_run: bool = True, allow_entity_id_change: bool = False) -> dict[str, Any]:
    eid = (entity_id or "").strip()
    new_name = (name or "").strip()
    if not eid or not new_name:
        return {"ok": False, "error": "entity_id_and_name_required"}
    if allow_entity_id_change:
        return {"ok": False, "error": "entity_id_change_not_supported_here", "hint": "Use a separate audited flow."}
    registry = list_entity_registry(limit=2000)
    if not registry.get("ok"):
        return registry
    before = _registry_lookup(registry.get("entities") or [], "entity_id", eid)
    if not before:
        return {"ok": False, "error": "entity_not_found", "entity_id": eid}
    if before.get("name") == new_name:
        return {"ok": True, "dry_run": dry_run, "changed": False, "reason": "already_named", "before": before, "after": before}
    payload = {"entity_id": eid, "name": new_name}
    if dry_run:
        return {"ok": True, "dry_run": True, "changed": True, "operation": "entity_registry_update_name", "payload": payload, "before": before, "rollback": {"entity_id": eid, "name": before.get("name")}}
    raw = ws_call("config/entity_registry/update", payload)
    if not raw.get("ok"):
        return raw
    after = raw.get("data") or {}
    return {"ok": True, "dry_run": False, "changed": True, "before": before, "after": after, "rollback": {"entity_id": eid, "name": before.get("name")}}


def ha_rename_device(device_id: str, name: str, *, dry_run: bool = True) -> dict[str, Any]:
    did = (device_id or "").strip()
    new_name = (name or "").strip()
    if not did or not new_name:
        return {"ok": False, "error": "device_id_and_name_required"}
    devices = list_devices(limit=2000)
    if not devices.get("ok"):
        return devices
    before = _registry_lookup(devices.get("devices") or [], "id", did)
    if not before:
        return {"ok": False, "error": "device_not_found", "device_id": did}
    current = before.get("name_by_user") or before.get("name")
    if current == new_name:
        return {"ok": True, "dry_run": dry_run, "changed": False, "reason": "already_named", "before": before, "after": before}
    payload = {"device_id": did, "name_by_user": new_name}
    if dry_run:
        return {"ok": True, "dry_run": True, "changed": True, "operation": "device_registry_update_name_by_user", "payload": payload, "before": before, "rollback": {"device_id": did, "name_by_user": before.get("name_by_user")}}
    raw = ws_call("config/device_registry/update", payload)
    if not raw.get("ok"):
        return raw
    after = raw.get("data") or {}
    return {"ok": True, "dry_run": False, "changed": True, "before": before, "after": after, "rollback": {"device_id": did, "name_by_user": before.get("name_by_user")}}


def find_device_by_mac(mac: str) -> dict[str, Any]:
    needle = (mac or "").replace(":", "").replace("-", "").lower()
    if not needle:
        return {"ok": False, "error": "mac_required"}
    devices = list_devices(limit=2000)
    if not devices.get("ok"):
        return devices
    matches = []
    for device in devices.get("devices") or []:
        haystack = json.dumps([device.get("connections"), device.get("identifiers")], ensure_ascii=False).replace(":", "").replace("-", "").lower()
        if needle in haystack:
            matches.append(device)
    if len(matches) != 1:
        return {"ok": False, "error": "device_match_not_unique", "matches": matches, "match_count": len(matches), "mac": mac}
    return {"ok": True, "device": matches[0]}


def ha_search_entity_references(entity_id: str) -> dict[str, Any]:
    eid = (entity_id or "").strip()
    if not eid:
        return {"ok": False, "error": "entity_id_required"}
    return ws_call("search/related", {"item_type": "entity", "item_id": eid})


def ha_batch_rename(items: list[dict[str, Any]] | str, *, dry_run: bool = True) -> dict[str, Any]:
    if isinstance(items, str):
        try:
            rows = json.loads(items)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": "invalid_items_json", "detail": str(exc)}
    else:
        rows = items
    if not isinstance(rows, list):
        return {"ok": False, "error": "items_must_be_list"}
    results = []
    for item in rows:
        if not isinstance(item, dict):
            results.append({"ok": False, "error": "item_must_be_object", "item": item})
            continue
        target_type = str(item.get("type") or item.get("target_type") or "entity").lower()
        if target_type == "device":
            device_id = str(item.get("device_id") or item.get("id") or "")
            if not device_id and item.get("mac"):
                found = find_device_by_mac(str(item.get("mac")))
                if not found.get("ok"):
                    results.append(found)
                    continue
                device_id = str((found.get("device") or {}).get("id") or "")
            results.append(ha_rename_device(device_id, str(item.get("name") or ""), dry_run=dry_run))
        elif target_type == "entity":
            results.append(ha_rename_entity_name(str(item.get("entity_id") or ""), str(item.get("name") or ""), dry_run=dry_run))
        else:
            results.append({"ok": False, "error": "unsupported_target_type", "target_type": target_type})
    return {"ok": all(r.get("ok") for r in results), "dry_run": dry_run, "count": len(results), "results": results}


def get_state(entity_id: str) -> dict[str, Any]:
    eid = (entity_id or "").strip()
    if not eid:
        return {"ok": False, "error": "entity_id_required"}
    raw = _request("GET", f"/api/states/{eid}")
    if not raw.get("ok"):
        return raw
    return {"ok": True, "entity": raw.get("data")}


def call_service(domain: str, service: str, *, entity_id: str | None = None, data: dict | None = None) -> dict[str, Any]:
    dom = (domain or "").strip()
    svc = (service or "").strip()
    if not dom or not svc:
        return {"ok": False, "error": "domain_and_service_required"}
    payload: dict[str, Any] = dict(data or {})
    if entity_id:
        payload["entity_id"] = entity_id
    raw = _request("POST", f"/api/services/{dom}/{svc}", json_body=payload)
    if not raw.get("ok"):
        return raw
    return {"ok": True, "domain": dom, "service": svc, "entity_id": entity_id, "data": payload}


def turn_on_light(entity_or_name: str) -> dict[str, Any]:
    eid = _resolve_light_entity(entity_or_name)
    if not eid:
        return {"ok": False, "error": "entity_not_found", "query": entity_or_name}
    domain = eid.split(".", 1)[0]
    return call_service(domain, "turn_on", entity_id=eid)


def turn_off_light(entity_or_name: str) -> dict[str, Any]:
    eid = _resolve_light_entity(entity_or_name)
    if not eid:
        return {"ok": False, "error": "entity_not_found", "query": entity_or_name}
    domain = eid.split(".", 1)[0]
    return call_service(domain, "turn_off", entity_id=eid)


def _resolve_entity(query: str, *, domain: str | None = None) -> str | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    if "." in q and q.split(".", 1)[0] in ("light", "switch", "scene", "climate"):
        return q
    # Alias de habitación
    for room, fragments in ROOM_ALIASES.items():
        if room in q or q in room:
            for dom in ([domain] if domain else ["light", "switch"]):
                items = list_states(domain=dom, limit=200)
                if not items.get("ok"):
                    continue
                for ent in items.get("entities") or []:
                    if ent.get("state") == "unavailable":
                        continue
                    eid = str(ent.get("entity_id") or "").lower()
                    name = str(ent.get("friendly_name") or "").lower()
                    if any(f in eid or f in name for f in fragments):
                        return str(ent.get("entity_id"))
    for dom in ([domain] if domain else ["light", "switch", "scene"]):
        if not dom:
            continue
        items = list_states(domain=dom, limit=200)
        if not items.get("ok"):
            continue
        for ent in items.get("entities") or []:
            if ent.get("state") == "unavailable":
                continue
            eid = str(ent.get("entity_id") or "")
            name = str(ent.get("friendly_name") or "").lower()
            slug = eid.split(".", 1)[-1].replace("_", " ")
            if q in eid.lower() or q in name or q in slug:
                return eid
    return None


def home_status(*, limit: int = 40) -> dict[str, Any]:
    """Estado resumido de la casa — luces e interruptores disponibles."""
    if not configured():
        return {"ok": False, "error": "ha_not_configured", "url": HA_URL}
    lights = list_states(domain="light", limit=limit)
    switches = list_states(domain="switch", limit=limit)
    if not lights.get("ok") and not switches.get("ok"):
        return lights if not lights.get("ok") else switches
    avail_l = [e for e in (lights.get("entities") or []) if e.get("state") != "unavailable"]
    avail_s = [e for e in (switches.get("entities") or []) if e.get("state") != "unavailable"]
    on_l = [e for e in avail_l if e.get("state") == "on"]
    on_s = [e for e in avail_s if e.get("state") == "on"]
    lines = [
        f"Home Assistant {HA_URL} — {len(avail_l)} luces, {len(avail_s)} interruptores disponibles.",
        f"Encendidas: {len(on_l)} luces, {len(on_s)} interruptores.",
    ]
    for e in avail_l[:12]:
        fn = e.get("friendly_name") or e.get("entity_id")
        lines.append(f"Luz {fn}: {e.get('state')}")
    for e in avail_s[:8]:
        fn = e.get("friendly_name") or e.get("entity_id")
        lines.append(f"Switch {fn}: {e.get('state')}")
    snapshot_cache(limit=limit)
    return {
        "ok": True,
        "url": HA_URL,
        "lights_available": len(avail_l),
        "switches_available": len(avail_s),
        "lights_on": len(on_l),
        "switches_on": len(on_s),
        "summary": "\n".join(lines),
        "entities": {"lights": avail_l, "switches": avail_s},
    }


def _resolve_light_entity(query: str) -> str | None:
    return _resolve_entity(query, domain="light") or _resolve_entity(query, domain="switch")


def snapshot_cache(*, limit: int = 120) -> dict[str, Any]:
    """Cache local de estados HA para RAG/digest sin golpear API cada segundo."""
    lights = list_states(domain="light", limit=limit)
    switches = list_states(domain="switch", limit=40)
    climate = list_states(domain="climate", limit=20)
    snapshot = {
        "ok": bool(lights.get("ok")),
        "ts": datetime.now(timezone.utc).isoformat(),
        "url": HA_URL,
        "lights": lights.get("entities") or [],
        "switches": switches.get("entities") or [] if switches.get("ok") else [],
        "climate": climate.get("entities") or [] if climate.get("ok") else [],
        "errors": [x for x in (lights, switches, climate) if not x.get("ok")],
    }
    try:
        HA_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        HA_STATE_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return snapshot


def read_cached_snapshot() -> dict[str, Any]:
    if not HA_STATE_FILE.is_file():
        return {"ok": False, "error": "no_cache"}
    try:
        return {"ok": True, **json.loads(HA_STATE_FILE.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
