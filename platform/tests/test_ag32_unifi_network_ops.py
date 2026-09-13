import importlib.util
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "homeassistant_client.py"
SPEC = importlib.util.spec_from_file_location("ag32_homeassistant_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
ha = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ha)


def _fixture_registry():
    return {
        "ok": True,
        "entities": [
            {"entity_id": "sensor.estudio_state", "original_name": "State", "device_id": "ap1"},
            {"entity_id": "sensor.estudio_memory_utilization", "original_name": "Memory utilization", "device_id": "ap1"},
            {"entity_id": "sensor.cuarto_state", "original_name": "State", "device_id": "ap2"},
            {"entity_id": "sensor.u7_lite_state", "original_name": "State", "device_id": "ap3"},
            {"entity_id": "sensor.u7_living_memory_utilization", "original_name": "Memory utilization", "device_id": "ap3"},
            {"entity_id": "sensor.rafahome2_4g_clients", "original_name": "Clients", "device_id": "w24a"},
            {"entity_id": "switch.rafahome2_4g_enabled", "original_name": "Enabled", "device_id": "w24a"},
            {"entity_id": "sensor.rafah2_4ghz_clients", "original_name": "Clients", "device_id": "w24b"},
            {"entity_id": "switch.rafah2_4ghz_enabled", "original_name": "Enabled", "device_id": "w24b"},
            {"entity_id": "sensor.rafahome5g_clients", "original_name": "Clients", "device_id": "w5"},
            {"entity_id": "switch.rafahome5g_enabled", "original_name": "Enabled", "device_id": "w5"},
        ],
    }


def _fixture_devices():
    return {
        "ok": True,
        "devices": [
            {"id": "ap1", "name": "Estudio", "manufacturer": "Ubiquiti Networks", "model": "U7HD", "sw_version": "1"},
            {"id": "ap2", "name": "Cuarto", "manufacturer": "Ubiquiti Networks", "model": "U7PG2", "sw_version": "1"},
            {"id": "ap3", "name": "U7 Living", "manufacturer": "Ubiquiti Networks", "model": "UAPA693", "sw_version": "1"},
            {"id": "w24a", "name": "RafaHome2.4G", "manufacturer": "Ubiquiti Networks", "model": "UniFi WLAN"},
            {"id": "w24b", "name": "RafaH2.4Ghz", "manufacturer": "Ubiquiti Networks", "model": "UniFi WLAN"},
            {"id": "w5", "name": "RafaHome5G", "manufacturer": "Ubiquiti Networks", "model": "UniFi WLAN"},
        ],
    }


def _fixture_states():
    states = {
        "sensor.estudio_state": "connected",
        "sensor.estudio_memory_utilization": "31.7",
        "sensor.cuarto_state": "unavailable",
        "sensor.u7_lite_state": "connected",
        "sensor.u7_living_memory_utilization": "81.1",
        "sensor.rafahome2_4g_clients": "27",
        "switch.rafahome2_4g_enabled": "on",
        "sensor.rafah2_4ghz_clients": "9",
        "switch.rafah2_4ghz_enabled": "on",
        "sensor.rafahome5g_clients": "10",
        "switch.rafahome5g_enabled": "on",
    }
    return {"ok": True, "data": [{"entity_id": key, "state": value, "attributes": {}} for key, value in states.items()]}


def test_unifi_request_routes_to_dedicated_path():
    with mock.patch.object(ha, "unifi_network_ops", return_value={"ok": True, "mode": "unifi_network_ops"}) as unifi:
        out = ha.run_home_ops_cycle("revisa el wifi unifi que está lento")
    assert out["mode"] == "unifi_network_ops"
    assert out["entrypoint"] == "homeassistant_client.unifi_network_ops"
    unifi.assert_called_once()


def test_unifi_diagnostics_are_complete_and_fail_closed():
    with mock.patch.object(ha, "list_entity_registry", return_value=_fixture_registry()), mock.patch.object(
        ha, "list_devices", return_value=_fixture_devices()
    ), mock.patch.object(ha, "_request", return_value=_fixture_states()):
        out = ha.unifi_network_ops("arregla el wifi unifi y las cámaras están lentas")
    assert out["ok"] is True
    assert out["requested_repair"] is True
    assert out["before_after"]["before"]["clients_24ghz"] == 36
    assert out["before_after"]["before"]["clients_5ghz"] == 10
    codes = {finding["code"] for finding in out["findings"]}
    assert "ap_unavailable" in codes
    assert "24ghz_client_pressure" in codes
    assert "multiple_24ghz_wlans" in codes
    assert "ap_memory_high" in codes
    assert out["safe_actions_applied"] == []
    assert out["verification"]["read_only"] is True
    assert out["actions_requiring_approval"]
    assert out["limitations"]
