"""Normalize Home Assistant network, bus and gateway health for AG-60."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from inneros_core_runtime.protocol_catalog import inventory_protocol_coverage

NETWORK_STATE_LABELS = {"state", "connection", "connection status", "availability"}
UP_VALUES = {"connected", "online", "up"}
DOWN_VALUES = {"disconnected", "offline", "down", "isolated", "adoption_failed"}


def _date(value: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _reading(entity: dict[str, Any], state: dict[str, Any], now: datetime,
             freshness_seconds: int) -> dict[str, Any] | None:
    eid = str(entity.get("entity_id") or "")
    domain = eid.split(".", 1)[0]
    label = str(entity.get("original_name") or "").lower()
    attrs = state.get("attributes") or {}
    state_text = str(state.get("state") or "").strip().lower()
    platform = str(entity.get("platform") or "").strip().lower()
    is_connection = (
        domain == "device_tracker"
        or (domain == "binary_sensor" and attrs.get("device_class") == "connectivity")
        or (platform == "unifi" and label == "state")
        or (label in NETWORK_STATE_LABELS and domain in {"sensor", "binary_sensor"})
    )
    if not is_connection:
        return None
    at = state.get("last_updated") or state.get("last_changed")
    timestamp = _date(at)
    age = (now - timestamp).total_seconds() if timestamp else None
    if age is None or age < -60 or age > freshness_seconds:
        verdict = "STALE"
    elif state_text in UP_VALUES or (domain == "device_tracker" and state_text == "home"):
        verdict = "ONLINE"
    elif state_text in DOWN_VALUES or (domain == "device_tracker" and state_text == "not_home"):
        verdict = "OFFLINE"
    elif domain == "binary_sensor" and attrs.get("device_class") == "connectivity" and state_text in {"on", "off"}:
        verdict = "ONLINE" if state_text == "on" else "OFFLINE"
    else:
        verdict = "UNKNOWN"
    return {"entity_id": eid, "status": verdict, "raw_state": state_text,
            "observed_at": at, "source": "home_assistant_state"}


def normalize_snapshot(
    devices: list[dict[str, Any]], entities: list[dict[str, Any]],
    states: list[dict[str, Any]], providers: list[dict[str, Any]],
    *, observed_at: datetime | None = None, freshness_seconds: int = 600,
) -> dict[str, Any]:
    """Treat integration records as identities; only explicit fresh state proves health."""
    now = observed_at or datetime.now(timezone.utc)
    catalog = inventory_protocol_coverage(devices, entities, providers)
    states_by_id = {str(s["entity_id"]): s for s in states if s.get("entity_id")}
    entities_by_device: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        if entity.get("device_id"):
            entities_by_device.setdefault(str(entity["device_id"]), []).append(entity)
    for record in catalog["devices"]:
        related = entities_by_device.get(record["device_id"], [])
        observations = []
        for entity in related:
            state = states_by_id.get(str(entity.get("entity_id") or ""))
            if state:
                reading = _reading(entity, state, now, freshness_seconds)
                if reading:
                    observations.append(reading)
        verdicts = {r["status"] for r in observations if r["status"] in {"ONLINE", "OFFLINE"}}
        if len(verdicts) > 1:
            verdict = "CONFLICT"
        elif verdicts:
            verdict = next(iter(verdicts))
        elif any(r["status"] == "STALE" for r in observations):
            verdict = "STALE"
        else:
            verdict = "UNKNOWN"
        record["connectivity_status"] = verdict
        record["connectivity_evidence"] = observations
        record["verified"] = verdict in {"ONLINE", "OFFLINE"}
        record["via_device_id"] = record.get("via_device_id")
        record["last_state_observed_at"] = max(
            (str(r["observed_at"]) for r in observations if r.get("observed_at")),
            default=None,
        )
    catalog["live_telemetry_verified"] = bool(states)
    catalog["observed_at"] = now.isoformat()
    return catalog


def live_home_snapshot(site_id: str = "home_pcdoctor_lab") -> dict[str, Any]:
    if site_id != "home_pcdoctor_lab":
        return {"ok": False, "error": "ha_site_not_mapped"}
    from raphiia_openai import homeassistant_client as ha
    from inneros_core_runtime.device_fabric import device_fabric_providers
    try:
        dev = ha.list_devices(limit=2000)
        ent = ha.list_entity_registry(limit=2000)
        state = ha._request("GET", "/api/states")
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    if not dev.get("ok") or not ent.get("ok"):
        return {"ok": False, "error": "ha_registry_unavailable"}
    if not state.get("ok"):
        # No live telemetry: preserve identities but do not mark devices online.
        snap = normalize_snapshot(dev.get("devices") or [], ent.get("entities") or [], [],
                                  device_fabric_providers().get("providers") or [])
        snap["gaps"] = ["ha_state_api_unavailable"]
        return snap
    return normalize_snapshot(dev.get("devices") or [], ent.get("entities") or [],
                              state.get("data") or [],
                              device_fabric_providers().get("providers") or [])
