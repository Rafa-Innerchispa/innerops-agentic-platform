"""Regression tests for truthful AG-60 Home Assistant inventory."""
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "device_fabric.py"
SPEC = importlib.util.spec_from_file_location("candidate_ag60_device_fabric", MODULE_PATH)
device_fabric = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(device_fabric)


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
    observed_at = datetime.now(timezone.utc).isoformat()
    states = {"ok": True, "data": [
        {"entity_id": "sensor.estudio_state", "state": "connected",
         "last_updated": observed_at},
        {"entity_id": "sensor.cuarto_state", "state": "unavailable",
         "last_updated": observed_at},
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


def test_stale_ap_state_never_verifies_online():
    observed = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    registry = {"ok": True, "entities": [
        {"device_id": "ap-1", "entity_id": "sensor.estudio_state",
         "original_name": "State", "platform": "unifi"}
    ]}
    states = {"ok": True, "data": [
        {"entity_id": "sensor.estudio_state", "state": "connected",
         "last_updated": observed}
    ]}
    with patch("inneros_core_runtime.homeassistant_client.list_devices", return_value=_devices()), patch(
        "inneros_core_runtime.homeassistant_client.list_entity_registry", return_value=registry
    ), patch("inneros_core_runtime.homeassistant_client._request", return_value=states):
        rows, _, _ = device_fabric._home_assistant_inventory()
    assert {r["name"]: r for r in rows}["Estudio"]["health"]["status"] == "STALE"


def test_home_lookup_reuses_stable_asset_id():
    rows = [
        {"asset_id": "123abc", "provider_device_id": "ap-1", "name": "Estudio",
         "mac": "aa:bb:cc:00:00:01", "ip": "192.168.1.20"}
    ]
    with patch.object(device_fabric, "_mongo_db", return_value=None), patch.object(
        device_fabric, "_home_assistant_inventory", return_value=(rows, {}, [])
    ):
        found = device_fabric.device_fabric_get("192.168.1.20", site_id="home_pcdoctor_lab")
    assert found["ok"] is True
    assert found["device"]["asset_id"] == "123abc"
