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
    elif domain == "device_tracker" and state_text == "not_home":
        # Away/presence is not proof of device failure.
        verdict = "NOT_PRESENT"
    elif state_text in DOWN_VALUES:
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
    catalog["live_telemetry_verified"] = any(row["verified"] for row in catalog["devices"])
    catalog["solar_edge_sources"] = edge_source_heartbeats(states, now)
    catalog["observed_at"] = now.isoformat()
    return catalog




SOLAR_EDGE_ENTITIES = (
    "sensor.inneros_pi01_solar_status",
    "sensor.inneros_pi01_solar_output_power",
    "sensor.inneros_pi01_solar_battery_voltage",
    "sensor.inneros_pi01_solar_mode",
    "binary_sensor.inneros_pi01_solar_grid_present",
)


def edge_source_heartbeats(states: list[dict[str, Any]],
                           now: datetime | None = None,
                           freshness_seconds: int = 900) -> list[dict[str, Any]]:
    """Monitor freshness of source telemetry, not inverter/panel functional health."""
    current = now or datetime.now(timezone.utc)
    indexed = {str(s.get("entity_id")): s for s in states}
    heartbeats = []
    for entity_id in SOLAR_EDGE_ENTITIES:
        row = indexed.get(entity_id)
        when = _date((row or {}).get("last_updated") or (row or {}).get("last_changed"))
        age = (current - when).total_seconds() if when else None
        online = (row is not None and age is not None and -60 <= age <= freshness_seconds
                  and str(row.get("state") or "").lower() not in {"unknown", "unavailable", ""})
        heartbeats.append({
            "entity_id": entity_id,
            "source": "home_assistant_solar_pi01",
            "telemetry_fresh": bool(online),
            "status": "FRESH" if online else "UNKNOWN_OR_STALE",
            "last_updated": (row or {}).get("last_updated"),
            "physical_usb_link_verified": False,
        })
    return heartbeats

def live_home_snapshot(site_id: str = "home_pcdoctor_lab") -> dict[str, Any]:
    if site_id != "home_pcdoctor_lab":
        return {"ok": False, "error": "ha_site_not_mapped"}
    from inneros_core_runtime import homeassistant_client as ha
    from inneros_core_runtime.device_fabric import device_fabric_providers
    try:
        dev = ha.list_devices(limit=2000)
        ent = ha.list_entity_registry(limit=2000)
        state = ha._request("GET", "/api/states")
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    if not dev.get("ok") or not ent.get("ok"):
        return {"ok": False, "error": "ha_registry_unavailable"}
    from inneros_core_runtime.physical_bus_observer import gateway_impact, host_observation

    live_states = state.get("data") or [] if state.get("ok") else []
    snap = normalize_snapshot(dev.get("devices") or [], ent.get("entities") or [],
                              live_states, device_fabric_providers().get("providers") or [])
    snap["gaps"] = [] if state.get("ok") else ["ha_state_api_unavailable"]
    snap["gateway_findings"] = gateway_impact(snap.get("devices") or [])
    # Covers USB, serial, NIC and Tailscale only on THIS executor host.
    snap["collector_host"] = host_observation()
    snap["remote_pi01_usb_verified"] = False
    snap["read_only"] = True
    return snap
