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
    # Controller telemetry: link, PoE, AP state, radio channel and client roaming.
    old_ctrl = previous.get("unifi_controller") or {}
    new_ctrl = current.get("unifi_controller") or {}
    if old_ctrl.get("ok") and new_ctrl.get("ok"):
        old_devices = {str(d.get("id")): d for d in old_ctrl.get("devices", []) if d.get("id")}
        for device in new_ctrl.get("devices", []):
            prior = old_devices.get(str(device.get("id")))
            if not prior:
                continue
            old_state = str(prior.get("state") or "").upper()
            state = str(device.get("state") or "").upper()
            if old_state != state and old_state and state:
                events.append({"type": "UNIFI_DEVICE_STATE_CHANGED", "severity": "warning",
                               "device": device.get("name"), "prior": old_state, "current": state,
                               "site_id": current.get("site_id"), "observed_at": ts})
            if prior.get("uplink_device_id") != device.get("uplink_device_id"):
                events.append({"type": "UNIFI_UPLINK_CHANGED", "severity": "warning",
                               "device": device.get("name"),
                               "from_device": prior.get("uplink_device_id"),
                               "to_device": device.get("uplink_device_id"),
                               "site_id": current.get("site_id"), "observed_at": ts})
            previous_ports = {str(p.get("idx")): p for p in prior.get("ports", []) if p.get("idx") is not None}
            for port in device.get("ports", []):
                before = previous_ports.get(str(port.get("idx")))
                if not before:
                    continue
                if before.get("state") != port.get("state"):
                    events.append({"type": "UNIFI_PORT_STATE_CHANGED", "severity": "warning",
                                   "device": device.get("name"), "port": port.get("idx"),
                                   "prior": before.get("state"), "current": port.get("state"),
                                   "site_id": current.get("site_id"), "observed_at": ts})
                poe_prev = (before.get("poe") or {}).get("state")
                poe_new = (port.get("poe") or {}).get("state")
                if poe_prev != poe_new and poe_prev is not None and poe_new is not None:
                    events.append({"type": "POE_STATE_CHANGED", "severity": "warning",
                                   "device": device.get("name"), "port": port.get("idx"),
                                   "prior": poe_prev, "current": poe_new,
                                   "site_id": current.get("site_id"), "observed_at": ts})
            previous_radios = {str(r.get("frequencyGHz")): r for r in prior.get("radios", [])}
            for radio in device.get("radios", []):
                before = previous_radios.get(str(radio.get("frequencyGHz")))
                if before and (before.get("channel"), before.get("channelWidthMHz")) != (
                    radio.get("channel"), radio.get("channelWidthMHz")
                ):
                    events.append({"type": "WIFI_RADIO_CHANNEL_CHANGED", "severity": "info",
                                   "device": device.get("name"),
                                   "frequency_ghz": radio.get("frequencyGHz"),
                                   "prior": {"channel": before.get("channel"), "width_mhz": before.get("channelWidthMHz")},
                                   "current": {"channel": radio.get("channel"), "width_mhz": radio.get("channelWidthMHz")},
                                   "site_id": current.get("site_id"), "observed_at": ts})
        old_clients = {str(c.get("mac") or "").lower(): c for c in old_ctrl.get("clients", []) if c.get("mac")}
        for client in new_ctrl.get("clients", []):
            former = old_clients.get(str(client.get("mac") or "").lower())
            if former and former.get("upstream_device_id") and client.get("upstream_device_id") and (
                former["upstream_device_id"] != client["upstream_device_id"]
            ):
                events.append({"type": "WIRELESS_CLIENT_ROAM", "severity": "info",
                               "client_mac": client.get("mac"),
                               "prior_ap": former.get("upstream_device_id"),
                               "new_ap": client.get("upstream_device_id"),
                               "site_id": current.get("site_id"), "observed_at": ts})
    elif old_ctrl.get("ok") and not new_ctrl.get("ok"):
        events.append({"type": "UNIFI_CONTROLLER_TELEMETRY_LOST", "severity": "warning",
                       "site_id": current.get("site_id"), "observed_at": ts,
                       "device_failure_confirmed": False})
    if old_bus.get("host") and old_bus.get("host") == bus.get("host"):
        old_ts = (old_bus.get("tailscale") or {}).get("backend_state")
        new_ts = (bus.get("tailscale") or {}).get("backend_state")
        if old_ts and new_ts and old_ts != new_ts:
            events.append({"type": "TAILSCALE_BACKEND_CHANGED", "severity": "warning",
                           "host": bus.get("host"), "prior": old_ts, "current": new_ts,
                           "site_id": current.get("site_id"), "observed_at": ts})
        previous_int = {i.get("interface"): i for i in old_bus.get("interfaces", [])}
        for nic in bus.get("interfaces", []):
            prior = previous_int.get(nic.get("interface"))
            if not prior:
                continue
            for field in ("rx_errors", "tx_errors", "rx_dropped", "tx_dropped"):
                try:
                    delta = int((nic.get("errors") or {}).get(field) or 0) - int(
                        (prior.get("errors") or {}).get(field) or 0)
                except (ValueError, TypeError):
                    continue
                if delta > 0:
                    events.append({"type": "NETWORK_INTERFACE_ERRORS_INCREASED",
                                   "severity": "warning", "host": bus.get("host"),
                                   "interface": nic.get("interface"), "counter": field,
                                   "delta": delta, "site_id": current.get("site_id"),
                                   "observed_at": ts, "cause": "UNDETERMINED"})
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
                "unifi_controller": snapshot.get("unifi_controller", {}),
                "critical_hosts": snapshot.get("critical_hosts", []),
                "gateway_findings": snapshot.get("gateway_findings", []),
                "gaps": snapshot.get("gaps", []),
            }
            db.communication_observation.insert_one(compact)
            if events:
                db.communication_event.insert_many(events)
            return {"ok": True, "events": events, "events_written": len(events)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:160]}
