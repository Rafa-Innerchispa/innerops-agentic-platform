"""Offline test suite for official local UniFi GET-only API adapter."""
import importlib.util
import os
from pathlib import Path
from unittest import mock

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ag60_unifi_candidate",
    Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "unifi_readonly.py",
)
unifi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(unifi)


def test_unifi_only_authorized_subnet():
    result = unifi.read_unifi_site(controller="8.8.8.8", api_key="test")
    assert result["ok"] is False
    assert result["error"] == "controller_outside_authorized_site"


def test_unifi_key_missing_fails_closed():
    with mock.patch.dict(os.environ, {"UNIFI_LOCAL_API_KEY": ""}):
        result = unifi.read_unifi_site()
    assert result["ok"] is False
    assert result["error"] == "unifi_local_api_key_missing"


def test_get_only_disallows_unknown_queries():
    with pytest.raises(ValueError):
        unifi._get_json("192.168.1.1", "/v1/sites?token=bad", "test")
    with pytest.raises(ValueError):
        unifi._get_json("192.168.1.1", "/v1/sites/../other", "test")


def test_unifi_ap_switch_ports_clients_and_radio_details():
    paths = []

    def fake_get(host, path, key):
        assert host == "192.168.1.1"
        assert key == "TEST_KEY"
        paths.append(path)
        if path.startswith("/v1/sites?"):
            return {"data": [{"id": "site123"}], "totalCount": 1}
        if path.startswith("/v1/sites/site123/devices?"):
            return {"data": [{"id": "ap1", "name": "Estudio", "model": "U7HD",
                               "state": "ONLINE", "type": "ACCESS_POINT"}],
                    "totalCount": 1}
        if path.startswith("/v1/sites/site123/clients?"):
            return {"data": [{"id": "client1", "macAddress": "00:11:22:33:44:55",
                               "name": "Dahua", "type": "WIRELESS", "ssid": "RafaHome2.4G"}],
                    "totalCount": 1}
        if path == "/v1/sites/site123/devices/ap1":
            return {"data": {"ipAddress": "192.168.1.20", "state": "ONLINE",
                             "interfaces": {"ports": [{"idx": 0, "state": "UP",
                                                       "speedMbps": 1000}],
                                            "radios": [{"channel": 6, "channelWidthMHz": 20}]},
                             "uplink": {"deviceId": "sw1"}}}
        raise AssertionError(path)

    result = unifi.read_unifi_site(api_key="TEST_KEY", getter=fake_get)
    assert result["ok"] is True
    assert result["device_count"] == 1
    assert result["devices"][0]["uplink_device_id"] == "sw1"
    assert result["devices"][0]["ports"][0]["speedMbps"] == 1000
    assert result["devices"][0]["radios"][0]["channel"] == 6
    assert result["clients"][0]["ssid"] == "RafaHome2.4G"
    assert not any("POST" in p for p in paths)
