import sys
from pathlib import Path

import pytest

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import device_fabric


def test_device_fabric_providers_surface():
    res = device_fabric.device_fabric_providers()
    assert res.get("ok") is True
    provider_ids = [p["provider_id"] for p in res.get("providers", [])]
    assert "generic_network" in provider_ids
    assert "grandstream_gcc" in provider_ids
    assert "grandstream_gwn" in provider_ids
    assert "home_assistant" in provider_ids
    assert "hikvision" in provider_ids
    assert "dahua" in provider_ids
    assert "unifi" in provider_ids
    assert "zkteco" in provider_ids
    assert "axis" in provider_ids


def test_fingerprint_zkteco_banner():
    fp = device_fabric._fingerprint("10.0.0.50", [80, 443], {"http": {"body_snippet": "ZKTeco Access Control"}})
    assert fp["vendor"] == "ZKTeco"
    assert "zkteco" in fp["provider_ids"]


def test_bellini_inventory_segmentation():
    # Query Bellini inventory
    inv = device_fabric.device_fabric_inventory(client_id="bellini", site_id="bellini-i-ii")
    assert inv.get("ok") is True
    assert inv.get("client_id") == "bellini"
    assert inv.get("site_id") == "bellini-i-ii"
    assert inv.get("count") >= 10
    
    ips = [d.get("ip") for d in inv.get("inventory", [])]
    assert "192.168.3.1" in ips
    assert "192.168.3.2" in ips


def test_device_fabric_get_lookup():
    # Lookup gateway by IP
    gw = device_fabric.device_fabric_get("192.168.3.1")
    assert gw.get("ok") is True
    assert gw.get("kind") == "device"
    assert gw.get("device", {}).get("model") == "GCC6010"

    # Lookup AP by asset_id
    ap = device_fabric.device_fabric_get("bellini_ap_188")
    assert ap.get("ok") is True
    assert ap.get("device", {}).get("ip") == "192.168.3.188"


def test_device_fabric_mutation_policy_is_read_only():
    res = device_fabric.device_fabric_bind("192.168.3.1", "grandstream_gcc", dry_run=False)
    assert res.get("ok") is False
    assert res.get("error") == "live_bind_disabled_in_read_only_task"

    dry = device_fabric.device_fabric_bind("192.168.3.1", "grandstream_gcc", dry_run=True)
    assert dry.get("ok") is True
    assert dry.get("dry_run") is True


def test_ruijie_live_inventory_normalizes_switch(monkeypatch):
    from inneros_core_runtime import ruijie_reyee_client as rj

    fake_creds = object()
    monkeypatch.setattr(rj, "load_ruijie_credentials", lambda: (fake_creds, None))
    monkeypatch.setattr(rj, "resolve_group_id", lambda **kw: 4242)
    monkeypatch.setattr(
        rj,
        "fetch_full_network_snapshot",
        lambda **kw: {
            "ok": True,
            "devices": {
                "devices": {
                    "AP": [],
                    "Gateway": [],
                    "Switch": [{
                        "aliasName": "Switch Central Administracion",
                        "serialNumber": "RUIJIE-SW-1",
                        "productClass": "RG-ES",
                        "onlineStatus": "ON",
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "localIp": "192.168.3.172",
                        "softwareVersion": "1.2.3",
                        "groupName": "Bellini",
                    }],
                }
            },
            "switch_ports": [{
                "serial_number": "RUIJIE-SW-1",
                "ports": {"data": [{"port": 1, "status": "UP"}]},
            }],
        },
    )

    rows, meta = device_fabric._ruijie_bellini_live_inventory()
    assert meta["ok"] is True
    assert len(rows) == 1
    sw = rows[0]
    assert sw["ip"] == "192.168.3.172"
    assert sw["provider"] == "ruijie_reyee"
    assert sw["serial"] == "RUIJIE-SW-1"
    assert sw["health"]["reachable"] is True
    assert sw["ports"] == {"data": [{"port": 1, "status": "UP"}]}
