"""Cliente Home Assistant REST — domótica local sin créditos cloud."""

from __future__ import annotations

import json
import os
import re
import socket
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import websockets
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", override=True)
_CANONICAL_RUNTIME_ENV = Path("/home/rlopez/inneros/inneros_core/platform/.env")
if _CANONICAL_RUNTIME_ENV != (_ROOT / ".env") and _CANONICAL_RUNTIME_ENV.is_file():
    load_dotenv(_CANONICAL_RUNTIME_ENV, override=False)

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


# ---------------------------------------------------------------------------
# AG-32 Intelbras alarm operations
# ---------------------------------------------------------------------------

_ALARM_INTENT_KEYWORDS = (
    "alarma", "alarm", "intelbras", "interbras", "anm", "amt24", "amt 24",
    "anm24", "anm 24", "sirena", "panic", "pánico", "panico", "armar",
    "desarmar", "perimetral", "seguridad casa",
)
_ALARM_WRITE_KEYWORDS = (
    "arma", "armar", "activa", "activar", "desarma", "desarmar", "desactiva",
    "desactivar", "sirena", "pánico", "panico", "panic", "dispara",
)
_ALARM_APPROVAL_KEYWORDS = (
    "autorizo", "autorizado", "confirmo", "apruebo", "sí autorizo", "si autorizo",
)
_ALARM_DEVICE_TERMS = ("alarma", "alarm", "intelbras", "interbras", "anm", "amt")
_INTELBRAS_DEFAULT_HOST = os.getenv("INTELBRAS_ALARM_HOST", "192.168.1.202").strip()
_INTELBRAS_DEFAULT_PORT = int(os.getenv("INTELBRAS_ALARM_PORT", "9009") or "9009")


def _is_alarm_request(message: str) -> bool:
    text = (message or "").strip().lower()
    return any(keyword in text for keyword in _ALARM_INTENT_KEYWORDS)


def _requested_alarm_write(message: str) -> bool:
    return _requested_alarm_action(message) is not None


def _explicit_alarm_approval(message: str) -> bool:
    text = (message or "").strip().lower()
    return _is_alarm_request(text) and any(keyword in text for keyword in _ALARM_APPROVAL_KEYWORDS)


def _requested_alarm_action(message: str) -> str | None:
    text = (message or "").strip().lower()
    if re.search(r"\b(desarma|desarmar|desactiva|desactivar)\b", text):
        return "alarm_disarm"
    if re.search(r"\b(perimetral|noche|en casa|home|stay)\b", text) and re.search(r"\b(arma|armar|activa|activar)\b", text):
        return "alarm_arm_home"
    if re.search(r"\b(arma|armar|activa|activar)\b", text):
        return "alarm_arm_away"
    if re.search(r"\b(sirena|p[aá]nico|panico|panic|dispara)\b", text):
        return "blocked_alarm_panic_or_siren"
    return None


def _alarm_matches(value: Any) -> bool:
    haystack = json.dumps(value, ensure_ascii=False).lower()
    return any(term in haystack for term in _ALARM_DEVICE_TERMS)


def _alarm_control_panels(states: list[dict[str, Any]], alarm_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    panels = [row for row in states if str(row.get("entity_id") or "").startswith("alarm_control_panel.")]
    if not panels:
        return []
    registry_ids = {
        str(row.get("entity_id") or "")
        for row in alarm_entities
        if str(row.get("entity_id") or "").startswith("alarm_control_panel.")
    }
    matched = [row for row in panels if str(row.get("entity_id") or "") in registry_ids or _alarm_matches(row)]
    return matched or panels


def _alarm_panel_summary(panel: dict[str, Any]) -> dict[str, Any]:
    attrs = panel.get("attributes") or {}
    return {
        "entity_id": panel.get("entity_id"),
        "state": panel.get("state"),
        "friendly_name": attrs.get("friendly_name"),
        "supported_features": attrs.get("supported_features"),
        "changed_at": panel.get("last_changed"),
        "updated_at": panel.get("last_updated"),
    }


def _maybe_apply_alarm_action(message: str, panel_entity_id: str | None) -> dict[str, Any]:
    requested_action = _requested_alarm_action(message)
    requested_write = bool(requested_action)
    approved = _explicit_alarm_approval(message)
    if not requested_write:
        return {"requested_write": False, "approved": False, "executed": False}
    if requested_action == "blocked_alarm_panic_or_siren":
        return {
            "requested_write": True,
            "approved": approved,
            "executed": False,
            "blocked": True,
            "reason": "panic_or_siren_requires_manual_runbook",
        }
    if not panel_entity_id:
        return {
            "requested_write": True,
            "approved": approved,
            "executed": False,
            "blocked": True,
            "reason": "alarm_control_panel_missing",
        }
    if not approved:
        return {
            "requested_write": True,
            "approved": False,
            "executed": False,
            "blocked": True,
            "reason": "explicit_alarm_approval_required",
            "required_phrase": "Sí, autorizo armar/desarmar la alarma.",
            "proposed_service": f"alarm_control_panel.{requested_action}",
            "entity_id": panel_entity_id,
        }
    result = call_service("alarm_control_panel", requested_action, entity_id=panel_entity_id)
    return {
        "requested_write": True,
        "approved": True,
        "executed": bool(result.get("ok")),
        "service": requested_action,
        "entity_id": panel_entity_id,
        "result": result,
    }


def _tcp_connectivity_probe(host: str, port: int, timeout: float = 1.5) -> dict[str, Any]:
    if not host:
        return {"ok": False, "error": "host_missing"}
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, int(port)))
        return {"ok": True, "host": host, "port": int(port), "state": "open"}
    except (OSError, ValueError) as exc:
        return {"ok": False, "host": host, "port": int(port), "state": "closed_or_unreachable", "error": type(exc).__name__}
    finally:
        sock.close()


def alarm_intelbras_ops(message: str = "") -> dict[str, Any]:
    """Read-only Intelbras alarm discovery for AG-32 and FieldOps.

    The first phase is intentionally non-invasive: Home Assistant/UniFi
    inventory plus a TCP connect probe to the known local alarm service. It
    does not send protocol frames, arm/disarm, trigger panic, siren or PGM.
    """
    raw_states = _request("GET", "/api/states")
    registry = list_entity_registry(limit=2000)
    devices = list_devices(limit=2000)
    if not raw_states.get("ok") or not registry.get("ok") or not devices.get("ok"):
        return {
            "ok": False,
            "mode": "alarm_intelbras_ops",
            "error": "alarm_observation_failed",
            "states_ok": bool(raw_states.get("ok")),
            "registry_ok": bool(registry.get("ok")),
            "devices_ok": bool(devices.get("ok")),
        }

    states = raw_states.get("data") or []
    alarm_states = [row for row in states if _alarm_matches(row)]
    alarm_entities = [row for row in registry.get("entities") or [] if _alarm_matches(row)]
    alarm_devices = [row for row in devices.get("devices") or [] if _alarm_matches(row)]

    tracker = next(
        (row for row in alarm_states if str(row.get("entity_id") or "").startswith("device_tracker.")),
        alarm_states[0] if alarm_states else {},
    )
    attrs = tracker.get("attributes") or {}
    device = alarm_devices[0] if alarm_devices else {}
    connections = device.get("connections") or []
    mac = next((item[1] for item in connections if isinstance(item, list) and item and item[0] == "mac"), None)
    host = str(attrs.get("ip") or attrs.get("ip_address") or _INTELBRAS_DEFAULT_HOST or "").strip()
    port_probe = _tcp_connectivity_probe(host, _INTELBRAS_DEFAULT_PORT) if host else {"ok": False, "error": "host_missing"}
    alarm_control_panels = _alarm_control_panels(states, alarm_entities)
    alarm_panel_entities = [str(row.get("entity_id") or "") for row in alarm_control_panels if row.get("entity_id")]
    primary_panel = alarm_control_panels[0] if alarm_control_panels else {}
    primary_panel_entity = str(primary_panel.get("entity_id") or "")
    requested_write = _requested_alarm_write(message)
    action_result = _maybe_apply_alarm_action(message, primary_panel_entity or None)

    inferred = []
    if str(device.get("manufacturer") or "").lower() == "intelbras" or str(mac or "").lower().startswith("d8:36:5f"):
        inferred.append("intelbras_device")
    if port_probe.get("ok") and int(port_probe.get("port") or 0) == 9009:
        inferred.append("local_tcp_9009_open")
    if not alarm_control_panels:
        inferred.append("home_assistant_alarm_control_panel_missing")
    else:
        inferred.append("home_assistant_alarm_control_panel_present")

    safe_actions = []
    if port_probe.get("ok"):
        safe_actions.append("verified_tcp_connectivity_9009_without_protocol_frames")
    if tracker:
        safe_actions.append("verified_home_assistant_unifi_presence_tracker")
    if alarm_control_panels:
        safe_actions.append("read_home_assistant_alarm_control_panel_state")
    if action_result.get("executed"):
        safe_actions.append(f"executed_home_assistant_alarm_service:{action_result.get('service')}")

    actions_requiring_approval = [
        "Validate a mature local Intelbras integration against this exact model before reading zones through protocol frames.",
        "Configure Home Assistant alarm_control_panel only after credentials/protocol are confirmed.",
        "Arm/disarm require explicit owner approval and the Home Assistant alarm_control_panel entity.",
        "Panic, siren and PGM remain blocked until a physical runbook is validated.",
    ]
    if requested_write and not action_result.get("executed"):
        actions_requiring_approval.insert(0, f"Requested alarm state change was not executed: {action_result.get('reason') or 'approval_or_entity_missing'}.")
    elif action_result.get("executed"):
        actions_requiring_approval.insert(0, "Alarm state change was sent through Home Assistant after explicit owner approval.")

    summary_tail = (
        f"alarm_panel={primary_panel.get('state')} ({primary_panel_entity})."
        if primary_panel_entity
        else "No Home Assistant alarm_control_panel entity is present yet."
    )

    return {
        "ok": True,
        "mode": "alarm_intelbras_ops",
        "read_only": not bool(action_result.get("executed")),
        "requested_write": requested_write,
        "action_result": action_result,
        "summary": (
            "Intelbras alarm observed on LAN via Home Assistant/UniFi; "
            f"presence={tracker.get('state') or 'unknown'}, tcp_9009={port_probe.get('state')}. "
            f"{summary_tail}"
        ),
        "device": {
            "declared_model": os.getenv("INTELBRAS_ALARM_MODEL", "AMT24 Net / ANM 24 NET candidate"),
            "ha_name": device.get("name_by_user") or device.get("name") or attrs.get("friendly_name"),
            "manufacturer": device.get("manufacturer"),
            "model": device.get("model"),
            "entity_id": tracker.get("entity_id"),
            "presence_state": tracker.get("state"),
            "host": host,
            "mac": mac or attrs.get("mac") or attrs.get("mac_address"),
            "connections": connections,
        },
        "connectivity": {
            "home_assistant_entities": [row.get("entity_id") for row in alarm_states],
            "registry_entities": [row.get("entity_id") for row in alarm_entities],
            "alarm_control_panel_entities": alarm_panel_entities,
            "alarm_control_panels": [_alarm_panel_summary(row) for row in alarm_control_panels],
            "tcp_probe": port_probe,
            "inferred": inferred,
        },
        "safe_actions_applied": safe_actions,
        "actions_requiring_approval": actions_requiring_approval,
        "fieldops_security": {
            "capability": "read_only_alarm_presence_and_connectivity",
            "event_source": "home_assistant_alarm_control_panel_or_unifi_device_tracker_plus_tcp_probe",
            "can_verify_intrusion_state": bool(alarm_control_panels),
            "can_execute_alarm_actions": bool(alarm_control_panels),
            "alarm_actions_guard": "explicit_owner_approval_required",
        },
        "limitations": (
            [
                "Home Assistant currently exposes the panel as a UniFi device_tracker, not as alarm_control_panel.",
                "TCP 9009 confirms a local service is reachable but does not prove authenticated protocol compatibility.",
                "Zone, tamper, battery, power and armed/disarmed state need a validated Intelbras local integration or documented protocol adapter.",
            ]
            if not alarm_control_panels
            else [
                "Panic, siren and PGM remain blocked until physically validated.",
                "Arm/disarm are routed only through Home Assistant and require explicit owner approval.",
            ]
        ),
    }


# ---------------------------------------------------------------------------
# AG-32 UniFi / Wi-Fi operations
# ---------------------------------------------------------------------------

_UNIFI_INTENT_KEYWORDS = (
    "unifi", "wifi", "wi-fi", "wlan", "access point", "punto de acceso",
    "señal", "senal", "2.4", "5 ghz", "5ghz", "cámara lenta", "camara lenta",
)
_UNIFI_REPAIR_KEYWORDS = (
    "arregla", "arreglar", "corrige", "corregir", "optimiza", "optimizar",
    "repara", "reparar",
)


def _is_unifi_request(message: str) -> bool:
    text = (message or "").strip().lower()
    return any(keyword in text for keyword in _UNIFI_INTENT_KEYWORDS)


def _requested_unifi_repair(message: str) -> bool:
    text = (message or "").strip().lower()
    return any(keyword in text for keyword in _UNIFI_REPAIR_KEYWORDS)


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _unifi_group_entity(
    rows: list[dict[str, Any]],
    state_by_id: dict[str, dict[str, Any]],
    *,
    original_name: str | None = None,
    suffix: str | None = None,
) -> dict[str, Any] | None:
    for row in rows:
        if original_name and str(row.get("original_name") or "").lower() != original_name.lower():
            continue
        entity_id = str(row.get("entity_id") or "")
        if suffix and not entity_id.endswith(suffix):
            continue
        state_row = state_by_id.get(entity_id) or {}
        return {
            "entity_id": entity_id,
            "state": state_row.get("state"),
            "attributes": state_row.get("attributes") or {},
        }
    return None


def unifi_network_ops(message: str = "") -> dict[str, Any]:
    """Observe, diagnose, act safely, and verify the local UniFi network.

    The current Home Assistant integration provides device/WLAN state and client
    counts, but not complete RF telemetry. Radio/channel/power changes therefore
    fail closed until an audited controller adapter with rollback is available.
    """
    registry = list_entity_registry(limit=2000, integration="unifi")
    devices = list_devices(limit=2000)
    raw_states = _request("GET", "/api/states")
    if not registry.get("ok") or not devices.get("ok") or not raw_states.get("ok"):
        return {
            "ok": False,
            "mode": "unifi_network_ops",
            "error": "unifi_observation_failed",
            "registry_ok": bool(registry.get("ok")),
            "devices_ok": bool(devices.get("ok")),
            "states_ok": bool(raw_states.get("ok")),
        }

    state_rows = raw_states.get("data") or []
    state_by_id = {
        str(row.get("entity_id") or ""): row
        for row in state_rows
        if row.get("entity_id")
    }
    entity_rows = registry.get("entities") or []
    relevant_device_ids = {
        str(row.get("device_id")) for row in entity_rows if row.get("device_id")
    }
    device_rows = devices.get("devices") or []
    unifi_devices = {
        str(row.get("id")): row
        for row in device_rows
        if row.get("id")
        and (
            str(row.get("id")) in relevant_device_ids
            or "ubiquiti" in str(row.get("manufacturer") or "").lower()
            or "unifi" in str(row.get("model") or "").lower()
        )
    }

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in entity_rows:
        device_id = str(row.get("device_id") or "")
        if device_id:
            grouped.setdefault(device_id, []).append(row)

    aps: list[dict[str, Any]] = []
    wlans: list[dict[str, Any]] = []
    gateways: list[dict[str, Any]] = []

    for device_id, device in unifi_devices.items():
        name = str(device.get("name_by_user") or device.get("name") or device_id)
        model = str(device.get("model") or "")
        rows = grouped.get(device_id, [])

        if model == "UniFi WLAN":
            clients = (
                _unifi_group_entity(rows, state_by_id, original_name="Clients")
                or _unifi_group_entity(rows, state_by_id, suffix="_clients")
            )
            enabled = (
                _unifi_group_entity(rows, state_by_id, original_name="Enabled")
                or _unifi_group_entity(rows, state_by_id, suffix="_enabled")
            )
            wlans.append({
                "name": name,
                "device_id": device_id,
                "clients": _safe_int((clients or {}).get("state")),
                "enabled": (enabled or {}).get("state"),
                "clients_entity": (clients or {}).get("entity_id"),
                "enabled_entity": (enabled or {}).get("entity_id"),
            })
            continue

        if model in {"UniFi Network", "UniFi Network Application"}:
            continue

        state_ent = (
            _unifi_group_entity(rows, state_by_id, original_name="State")
            or _unifi_group_entity(rows, state_by_id, suffix="_state")
        )
        uptime_ent = (
            _unifi_group_entity(rows, state_by_id, original_name="Uptime")
            or _unifi_group_entity(rows, state_by_id, suffix="_uptime")
        )
        cpu_ent = (
            _unifi_group_entity(rows, state_by_id, original_name="CPU utilization")
            or _unifi_group_entity(rows, state_by_id, suffix="_cpu_utilization")
        )
        mem_ent = (
            _unifi_group_entity(rows, state_by_id, original_name="Memory utilization")
            or _unifi_group_entity(rows, state_by_id, suffix="_memory_utilization")
        )
        uplink_ent = (
            _unifi_group_entity(rows, state_by_id, original_name="Uplink MAC")
            or _unifi_group_entity(rows, state_by_id, suffix="_uplink_mac")
        )
        item = {
            "name": name,
            "device_id": device_id,
            "model": model,
            "software": device.get("sw_version"),
            "state": (state_ent or {}).get("state"),
            "uptime": (uptime_ent or {}).get("state"),
            "cpu_percent": _safe_int((cpu_ent or {}).get("state")),
            "memory_percent": _safe_int((mem_ent or {}).get("state")),
            "uplink_mac": (uplink_ent or {}).get("state"),
        }
        if "gateway" in name.lower() or model.upper() in {"UDRULT", "UDM", "UDMPRO", "UDR"}:
            gateways.append(item)
        elif state_ent or any(str(r.get("original_name") or "").lower() == "restart" for r in rows):
            aps.append(item)

    disconnected_states = {
        "unavailable", "disconnected", "heartbeat_missed", "isolated",
        "adoption_failed", "inform_error",
    }
    offline_aps = [
        ap for ap in aps if str(ap.get("state") or "").lower() in disconnected_states
    ]
    active_aps = [
        ap for ap in aps if str(ap.get("state") or "").lower() == "connected"
    ]
    high_memory_aps = [
        ap for ap in active_aps if (ap.get("memory_percent") or 0) >= 80
    ]

    clients_24 = 0
    clients_5 = 0
    wlans_24: list[dict[str, Any]] = []
    wlans_5: list[dict[str, Any]] = []
    for wlan in wlans:
        low = wlan["name"].lower()
        if "2.4" in low or "2_4" in low or "2-4" in low:
            wlans_24.append(wlan)
            clients_24 += wlan.get("clients") or 0
        elif "5g" in low or "5 ghz" in low or "5ghz" in low:
            wlans_5.append(wlan)
            clients_5 += wlan.get("clients") or 0

    findings: list[dict[str, Any]] = []
    likely_causes: list[str] = []

    if offline_aps:
        findings.append({
            "severity": "high",
            "code": "ap_unavailable",
            "detail": [ap["name"] for ap in offline_aps],
        })
        likely_causes.append(
            "One or more configured UniFi AP records are unavailable, reducing expected coverage or representing stale/replaced AP records."
        )
    if len(wlans_24) > 1:
        findings.append({
            "severity": "medium",
            "code": "multiple_24ghz_wlans",
            "detail": [w["name"] for w in wlans_24],
        })
        likely_causes.append(
            "Multiple 2.4 GHz WLANs may duplicate airtime and make client placement harder to reason about."
        )
    if clients_24 >= 25:
        findings.append({
            "severity": "high",
            "code": "24ghz_client_pressure",
            "detail": {"clients": clients_24, "wlans": len(wlans_24)},
        })
        likely_causes.append(
            "2.4 GHz carries a high client count; cameras and IoT compete for limited airtime, especially with weak RSSI or overlapping channels."
        )
    if high_memory_aps:
        findings.append({
            "severity": "medium",
            "code": "ap_memory_high",
            "detail": [
                {"name": ap["name"], "memory_percent": ap["memory_percent"]}
                for ap in high_memory_aps
            ],
        })
    if clients_24 > clients_5 * 2 and clients_24 >= 15:
        findings.append({
            "severity": "medium",
            "code": "band_imbalance",
            "detail": {"clients_24": clients_24, "clients_5": clients_5},
        })
        likely_causes.append(
            "Client distribution is heavily skewed toward 2.4 GHz instead of 5 GHz for capable devices."
        )

    requested_repair = _requested_unifi_repair(message)
    before = {
        "active_aps": [ap["name"] for ap in active_aps],
        "offline_or_stale_aps": [ap["name"] for ap in offline_aps],
        "clients_24ghz": clients_24,
        "clients_5ghz": clients_5,
        "wlans_24ghz": [w["name"] for w in wlans_24],
        "wlans_5ghz": [w["name"] for w in wlans_5],
    }

    limitations = [
        "Home Assistant exposes UniFi device/WLAN state, client counts, uptime and some resource telemetry, but not RF channel width, channel utilization, RSSI/retry rate, transmit power or interference on this integration surface.",
        "Channel, power, firmware, password and AP restart changes remain fail-closed until an audited controller adapter can verify the before/after state and rollback."
    ]
    actions_requiring_approval = [
        "Read per-radio channel, channel utilization, retry rate and client RSSI from the UniFi controller before RF changes.",
        "If contention is confirmed, coordinate non-overlapping 2.4 GHz channels, 20 MHz width, and 5 GHz steering/power tuning with rollback evidence.",
    ]
    if offline_aps:
        actions_requiring_approval.append(
            "Confirm whether unavailable AP records are intentionally disabled/replaced or physically offline before restart/removal/adoption."
        )

    return {
        "ok": True,
        "mode": "unifi_network_ops",
        "requested_repair": requested_repair,
        "summary": (
            f"UniFi observed: {len(active_aps)} AP(s) connected, {len(offline_aps)} unavailable/stale; "
            f"{clients_24} clients on identified 2.4 GHz WLANs and {clients_5} on identified 5 GHz WLANs."
        ),
        "findings": findings,
        "evidence": {"access_points": aps, "gateways": gateways, "wlans": wlans},
        "likely_causes": likely_causes,
        "safe_actions_applied": [],
        "actions_requiring_approval": actions_requiring_approval,
        "verification": {
            "performed": True,
            "source": "home_assistant_unifi_integration",
            "read_only": True,
            "consistent": True,
        },
        "before_after": {"before": before, "after": before, "changed": False},
        "limitations": limitations,
    }


def run_home_ops_cycle(trigger: str = "mcp") -> dict[str, Any]:
    """Canonical AG-32 entrypoint with intent-aware routing."""
    if _is_alarm_request(trigger):
        out = alarm_intelbras_ops(trigger)
        out.setdefault("trigger", trigger or "mcp")
        out["entrypoint"] = "homeassistant_client.alarm_intelbras_ops"
        return out
    if _is_unifi_request(trigger):
        out = unifi_network_ops(trigger)
        out.setdefault("trigger", trigger or "mcp")
        out["entrypoint"] = "homeassistant_client.unifi_network_ops"
        return out

    from raphiia_openai import home_ops_daemon

    out = home_ops_daemon.run_cycle()
    if isinstance(out, dict):
        out.setdefault("ok", True)
        out["trigger"] = trigger or "mcp"
        out["entrypoint"] = "homeassistant_client.run_home_ops_cycle"
        return out
    return {
        "ok": False,
        "error": "home_ops_cycle_invalid_result",
        "trigger": trigger or "mcp",
        "entrypoint": "homeassistant_client.run_home_ops_cycle",
    }
