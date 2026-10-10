"""Read-only USB/NIC/serial evidence and gateway dependency tests."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "ag60_physical_bus_candidate",
    Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "physical_bus_observer.py",
)
bus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bus)


def test_usb_identifies_solar_signature_without_fake_stream(tmp_path):
    device = tmp_path / "1-1"
    device.mkdir()
    (device / "idVendor").write_text("0665")
    (device / "idProduct").write_text("5161")
    found = bus.local_usb_devices(str(tmp_path))
    assert len(found) == 1
    assert found[0]["possible_xmart_pi01"] is True
    assert found[0]["data_stream_verified"] is False


def test_usb_missing_root_is_unknown_not_fake(tmp_path):
    assert bus.local_usb_devices(str(tmp_path / "absent")) == []


def test_nic_link_and_errors_read_only(tmp_path):
    iface = tmp_path / "enp3s0"
    (iface / "statistics").mkdir(parents=True)
    (iface / "operstate").write_text("up")
    (iface / "carrier").write_text("1")
    (iface / "statistics" / "rx_dropped").write_text("3")
    items = bus.local_interfaces(str(tmp_path))
    assert items[0]["state"] == "up"
    assert items[0]["errors"]["rx_dropped"] == "3"


def test_tailscale_does_not_claim_phone_routing_fixed():
    payload = {"BackendState": "Running", "Peer": {"peer1": {}, "peer2": {}}, "Health": []}
    response = mock.Mock(returncode=0, stdout=json.dumps(payload))
    with mock.patch.object(bus.subprocess, "run", return_value=response):
        snap = bus.tailscale_status()
    assert snap["ok"] is True
    assert snap["peer_count"] == 2
    assert snap["phone_client_dns_and_routes_checked"] is False


def test_gateway_impact_does_not_assert_root_cause():
    devices = [
        {"device_id": "gw", "name": "Zigbee Hub", "connectivity_status": "OFFLINE"},
        {"device_id": "sensor1", "name": "Sensor puerta", "via_device_id": "gw",
         "connectivity_status": "UNKNOWN"},
    ]
    impacted = bus.gateway_impact(devices)
    assert impacted[0]["gateway"] == "Zigbee Hub"
    assert impacted[0]["root_cause_confirmed"] is False
