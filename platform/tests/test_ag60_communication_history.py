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
