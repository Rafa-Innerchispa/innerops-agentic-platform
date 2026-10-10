"""AG-60 event correlation across devices, USB, ethernet and solar."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ag60_history_under_test",
    Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "communication_history.py",
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def state(value):
    return {"device_id": "ap1", "name": "Estudio", "connectivity_status": value}


def snap(value, bus=None, solar=None):
    return {"site_id": "home_pcdoctor_lab", "observed_at": "2026-10-09T12:00:00Z",
            "devices": [state(value)], "collector_host": bus or {},
            "solar_edge_sources": solar or []}


def test_up_down_is_disconnection():
    rows = mod.compare_snapshots(snap("ONLINE"), snap("OFFLINE"))
    assert rows[0]["type"] == "DEVICE_DISCONNECTED"


def test_lost_observability_not_marked_as_device_down():
    rows = mod.compare_snapshots(snap("ONLINE"), snap("UNKNOWN"))
    assert rows[0]["type"] == "TELEMETRY_GAP"
    assert rows[0]["root_cause_confirmed"] is False


def test_usb_loss_has_physical_host_evidence():
    old = {"host": "pi01", "usb": [{"bus_id": "1-1", "usb_id": "0665:5161"}]}
    new = {"host": "pi01", "usb": []}
    rows = mod.compare_snapshots(snap("ONLINE", bus=old), snap("ONLINE", bus=new))
    assert rows[0]["type"] == "USB_ADAPTER_MISSING"


def test_ethernet_loss_detected_on_same_host():
    old = {"host": "amd", "interfaces": [{"interface": "enp3s0", "carrier": "1"}]}
    new = {"host": "amd", "interfaces": [{"interface": "enp3s0", "carrier": "0"}]}
    rows = mod.compare_snapshots(snap("ONLINE", bus=old), snap("ONLINE", bus=new))
    assert rows[0]["type"] == "ETHERNET_CARRIER_LOST"


def test_solar_data_loss_is_not_equated_to_power_loss():
    before = [{"entity_id": "sensor.inneros_pi01_solar_output_power", "telemetry_fresh": True}]
    after = [{"entity_id": "sensor.inneros_pi01_solar_output_power", "telemetry_fresh": False}]
    rows = mod.compare_snapshots(snap("ONLINE", solar=before), snap("ONLINE", solar=after))
    assert rows[0]["type"] == "SOLAR_TELEMETRY_STALE"
    assert rows[0]["power_failure_confirmed"] is False


def test_unifi_port_poe_radio_uplink_and_roam_are_audited():
    previous = snap("ONLINE")
    current = snap("ONLINE")
    previous["unifi_controller"] = {
        "ok": True,
        "devices": [{
            "id": "ap1", "name": "Estudio", "state": "ONLINE",
            "uplink_device_id": "switch1",
            "ports": [{"idx": 0, "state": "UP", "poe": {"state": "UP"}}],
            "radios": [{"frequencyGHz": 2.4, "channel": 1, "channelWidthMHz": 20}],
        }],
        "clients": [{"mac": "aa:bb", "upstream_device_id": "ap1"}],
    }
    current["unifi_controller"] = {
        "ok": True,
        "devices": [{
            "id": "ap1", "name": "Estudio", "state": "OFFLINE",
            "uplink_device_id": "switch2",
            "ports": [{"idx": 0, "state": "DOWN", "poe": {"state": "DOWN"}}],
            "radios": [{"frequencyGHz": 2.4, "channel": 6, "channelWidthMHz": 20}],
        }],
        "clients": [{"mac": "aa:bb", "upstream_device_id": "ap2"}],
    }
    kinds = {e["type"] for e in mod.compare_snapshots(previous, current)}
    assert {
        "UNIFI_DEVICE_STATE_CHANGED",
        "UNIFI_UPLINK_CHANGED",
        "UNIFI_PORT_STATE_CHANGED",
        "POE_STATE_CHANGED",
        "WIFI_RADIO_CHANNEL_CHANGED",
        "WIRELESS_CLIENT_ROAM",
    }.issubset(kinds)


def test_increasing_nic_errors_and_tailscale_change():
    old = {"host": "amd", "interfaces": [
        {"interface": "enp3s0", "carrier": "1", "errors": {"rx_errors": "0"}}],
        "tailscale": {"backend_state": "Running"}}
    new = {"host": "amd", "interfaces": [
        {"interface": "enp3s0", "carrier": "1", "errors": {"rx_errors": "4"}}],
        "tailscale": {"backend_state": "Stopped"}}
    kinds = {e["type"] for e in mod.compare_snapshots(snap("ONLINE", bus=old),
                                                       snap("ONLINE", bus=new))}
    assert "NETWORK_INTERFACE_ERRORS_INCREASED" in kinds
    assert "TAILSCALE_BACKEND_CHANGED" in kinds


def test_critical_host_loss_is_unverified_network_issue():
    previous, current = snap("ONLINE"), snap("ONLINE")
    previous["critical_hosts"] = [{"label": "pi01_solar_bridge", "health": "ONLINE", "ip": "192.168.1.97"}]
    current["critical_hosts"] = [{"label": "pi01_solar_bridge", "health": "UNKNOWN", "ip": "192.168.1.97"}]
    events = mod.compare_snapshots(previous, current)
    event = next(e for e in events if e["type"] == "CRITICAL_HOST_REACHABILITY_CHANGED")
    assert event["physical_outage_proven"] is False
