"""Diff communication snapshots and store evidence without fabricating outages."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any


def compare_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    old = {d.get("device_id"): d for d in previous.get("devices", []) if d.get("device_id")}
    new = {d.get("device_id"): d for d in current.get("devices", []) if d.get("device_id")}
    ts = current.get("observed_at") or datetime.now(timezone.utc).isoformat()
    events: list[dict[str, Any]] = []
    for device_id, item in new.items():
        prior = old.get(device_id)
        if not prior:
            continue
        old_status = str(prior.get("connectivity_status") or "UNKNOWN")
        status = str(item.get("connectivity_status") or "UNKNOWN")
        if old_status == status:
            continue
        # Unknown/stale is a telemetry gap, not proof a device is disconnected.
        if status in {"UNKNOWN", "STALE", "CONFLICT"}:
            event = "TELEMETRY_GAP"
            severity = "warning"
        elif old_status == "ONLINE" and status == "OFFLINE":
            event = "DEVICE_DISCONNECTED"
            severity = "high"
        elif old_status == "OFFLINE" and status == "ONLINE":
            event = "DEVICE_RECONNECTED"
            severity = "info"
        else:
            event = "CONNECTIVITY_OBSERVED"
            severity = "info"
        events.append({"type": event, "severity": severity,
                       "site_id": current.get("site_id"), "device_id": device_id,
                       "name": item.get("name"), "prior": old_status,
                       "current": status, "observed_at": ts,
                       "source": "home_assistant_connectivity",
                       "root_cause_confirmed": False})
    old_bus = previous.get("collector_host") or {}
    bus = current.get("collector_host") or {}
    if old_bus.get("host") and old_bus.get("host") == bus.get("host"):
        old_usb = {(d.get("bus_id"), d.get("usb_id")) for d in old_bus.get("usb", [])}
        new_usb = {(d.get("bus_id"), d.get("usb_id")) for d in bus.get("usb", [])}
        for bus_id, usb_id in sorted(old_usb - new_usb):
            events.append({"type": "USB_ADAPTER_MISSING", "severity": "high",
                           "site_id": current.get("site_id"), "observed_at": ts,
                           "bus_id": bus_id, "usb_id": usb_id,
                           "host": bus["host"], "root_cause_confirmed": False})
        old_interfaces = {i["interface"]: i for i in old_bus.get("interfaces", []) if i.get("interface")}
        for item in bus.get("interfaces", []):
            prior = old_interfaces.get(item.get("interface"))
            if prior and prior.get("carrier") == "1" and item.get("carrier") == "0":
                events.append({"type": "ETHERNET_CARRIER_LOST", "severity": "high",
                               "site_id": current.get("site_id"), "observed_at": ts,
                               "interface": item.get("interface"), "host": bus["host"],
                               "root_cause_confirmed": False})
    before_solar = {row.get("entity_id"): row for row in previous.get("solar_edge_sources", [])}
    for item in current.get("solar_edge_sources", []):
        prior = before_solar.get(item.get("entity_id"))
        if prior and prior.get("telemetry_fresh") and not item.get("telemetry_fresh"):
            events.append({"type": "SOLAR_TELEMETRY_STALE", "severity": "warning",
                           "site_id": current.get("site_id"), "observed_at": ts,
                           "entity_id": item.get("entity_id"),
                           "power_failure_confirmed": False, "usb_failure_confirmed": False})
    return events


def write_history(snapshot: dict[str, Any], mongo_uri: str | None = None) -> dict[str, Any]:
    """Store reduced snapshots in the site's local MongoDB. This never writes to devices."""
    try:
        from pymongo import MongoClient
        with MongoClient(mongo_uri or os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017"),
                         serverSelectionTimeoutMS=1500) as client:
            db = client["pcdoctor_swarm"]
            site_id = snapshot["site_id"]
            prior = db.communication_observation.find_one(
                {"site_id": site_id}, sort=[("observed_at", -1)], projection={"_id": 0}) or {}
            events = compare_snapshots(prior, snapshot)
            compact = {
                "site_id": site_id,
                "observed_at": snapshot.get("observed_at"),
                "devices": snapshot.get("devices", []),
                "solar_edge_sources": snapshot.get("solar_edge_sources", []),
                "collector_host": snapshot.get("collector_host", {}),
                "gateway_findings": snapshot.get("gateway_findings", []),
                "gaps": snapshot.get("gaps", []),
            }
            db.communication_observation.insert_one(compact)
            if events:
                db.communication_event.insert_many(events)
            return {"ok": True, "events": events, "events_written": len(events)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:160]}
