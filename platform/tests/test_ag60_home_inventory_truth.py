"""Regression tests for truthful AG-60 Home Assistant inventory."""
from unittest.mock import patch
from inneros_core_runtime import device_fabric


def _devices():
    return {"ok": True, "devices": [
        {"id": "ap-1", "name": "Estudio", "manufacturer": "Ubiquiti Networks",
         "model": "U7HD", "connections": [["mac", "aa:bb:cc:00:00:01"]]},
        {"id": "ap-2", "name": "Cuarto", "manufacturer": "Ubiquiti Networks",
         "model": "U7PG2"},
        {"id": "nvr-1", "name": "NVR Dahua", "manufacturer": "Dahua",
         "model": "NVR"},
    ]}


def test_unknown_devices_are_not_online():
    item = device_fabric.canonical_device_record(
        tenant_id="innerchispa", client_id="pcdoctor_lab",
        site_id="home_pcdoctor_lab", name="unprobed"
    )
    assert item["health"]["status"] == "UNKNOWN"
    assert item["health"]["reachable"] is None
    assert item["last_seen"] is None


def test_ha_inventory_differentiates_ap_state_and_nvr_unknown():
    registry = {"ok": True, "entities": [
        {"device_id": "ap-1", "entity_id": "sensor.estudio_state",
         "original_name": "State", "platform": "unifi"},
        {"device_id": "ap-2", "entity_id": "sensor.cuarto_state",
         "original_name": "State", "platform": "unifi"},
    ]}
    states = {"ok": True, "data": [
        {"entity_id": "sensor.estudio_state", "state": "connected",
         "last_updated": "2026-10-09T15:00:00Z"},
        {"entity_id": "sensor.cuarto_state", "state": "unavailable",
         "last_updated": "2026-10-09T15:00:01Z"},
    ]}
    with patch("inneros_core_runtime.homeassistant_client.list_devices", return_value=_devices()), patch(
        "inneros_core_runtime.homeassistant_client.list_entity_registry", return_value=registry
    ), patch("inneros_core_runtime.homeassistant_client._request", return_value=states):
        rows, _, blockers = device_fabric._home_assistant_inventory()
    assert blockers == []
    devices = {r["name"]: r for r in rows}
    assert devices["Estudio"]["health"]["status"] == "ONLINE"
    assert devices["Cuarto"]["health"]["status"] == "OFFLINE"
    assert devices["Cuarto"]["health"]["reachable"] is False
    assert devices["NVR Dahua"]["health"]["status"] == "UNKNOWN"
    assert devices["Estudio"]["mac"] == "aa:bb:cc:00:00:01"
    assert devices["Cuarto"]["last_seen"] is None


def test_missing_state_api_fails_closed():
    with patch("inneros_core_runtime.homeassistant_client.list_devices", return_value=_devices()), patch(
        "inneros_core_runtime.homeassistant_client.list_entity_registry", return_value={"ok": True, "entities": []}
    ), patch("inneros_core_runtime.homeassistant_client._request", return_value={"ok": False}):
        rows, _, blockers = device_fabric._home_assistant_inventory()
    assert blockers
    assert all(r["health"]["status"] == "UNKNOWN" for r in rows)
