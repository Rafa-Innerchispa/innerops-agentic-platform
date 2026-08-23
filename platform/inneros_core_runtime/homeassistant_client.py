"""Cliente Home Assistant REST — domótica local sin créditos cloud."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
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
