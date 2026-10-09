"""AG-60 vendor-neutral collector tests. No live LAN required."""
from datetime import datetime, timedelta, timezone

from inneros_core_runtime.protocol_catalog import inventory_protocol_coverage
from inneros_core_runtime.communication_observer import (
    edge_source_heartbeats, normalize_snapshot,
)


NOW = datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc)


def _dev(name="Estudio"):
    return [{"id": "ap-1", "name": name, "manufacturer": "Ubiquiti",
             "model": "U7HD", "via_device_id": "switch-1"}]


def _entity(platform="unifi", label="State"):
    return [{"device_id": "ap-1", "entity_id": "sensor.ap_state",
             "platform": platform, "original_name": label}]


def _state(value="connected", timestamp=NOW):
    return [{"entity_id": "sensor.ap_state", "state": value,
             "last_updated": timestamp.isoformat(), "attributes": {}}]


def test_fresh_unifi_state_is_verified_with_parent():
    r = normalize_snapshot(_dev(), _entity(), _state(), [], observed_at=NOW)
    record = r["devices"][0]
    assert record["connectivity_status"] == "ONLINE"
    assert record["verified"] is True
    assert record["via_device_id"] == "switch-1"
    assert "wifi" in record["protocol_hints"]


def test_stale_unifi_state_not_online():
    old = NOW - timedelta(hours=2)
    r = normalize_snapshot(_dev(), _entity(), _state(timestamp=old), [],
                           observed_at=NOW)
    assert r["devices"][0]["connectivity_status"] == "STALE"
    assert r["devices"][0]["verified"] is False


def test_missing_source_stays_unknown():
    r = normalize_snapshot(_dev(), _entity(), [], [], observed_at=NOW)
    assert r["devices"][0]["connectivity_status"] == "UNKNOWN"


def test_generic_mqtt_does_not_imply_zigbee():
    rows = [{"id": "x", "name": "Unknown vendor"}]
    reg = [{"device_id": "x", "platform": "mqtt"}]
    r = inventory_protocol_coverage(rows, reg, [])
    assert "mqtt" in r["devices"][0]["protocol_hints"]
    assert "zigbee" not in r["devices"][0]["protocol_hints"]


def test_tracker_absence_not_device_failure():
    reg = [{"device_id": "ap-1", "platform": "unifi",
            "entity_id": "device_tracker.phone", "original_name": "Phone"}]
    states = [{"entity_id": "device_tracker.phone", "state": "not_home",
               "last_updated": NOW.isoformat(), "attributes": {}}]
    r = normalize_snapshot(_dev(), reg, states, [], observed_at=NOW)
    assert r["devices"][0]["connectivity_status"] == "UNKNOWN"


def test_solar_heartbeat_measures_freshness_not_usb():
    states = [{"entity_id": "sensor.inneros_pi01_solar_status", "state": "online",
               "last_updated": NOW.isoformat()}]
    rows = edge_source_heartbeats(states, NOW)
    solar = next(x for x in rows if x["entity_id"] == "sensor.inneros_pi01_solar_status")
    assert solar["status"] == "FRESH"
    assert solar["physical_usb_link_verified"] is False
    assert len(rows) >= 5
