"""Tests for Ruijie / Reyee Cloud OpenAPI Adapter and Device Fabric integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from inneros_core_runtime import device_fabric
from inneros_core_runtime import ruijie_reyee_client as rrc


def test_load_ruijie_credentials_and_redaction():
    creds, err = rrc.load_ruijie_credentials()
    assert creds is not None, f"Failed to load credentials: {err}"
    assert err is None
    assert creds.app_id == "open965a3e3225d5"
    assert creds.secret_key != ""

    # Test as_public() sanitization
    public_dict = creds.as_public()
    assert public_dict["app_id"] == "open965a3e3225d5"
    assert public_dict["secret_configured"] is True
    assert "secret_key" not in public_dict

    # Test recursive redaction
    redacted = rrc._redact({
        "app_id": "open965a3e3225d5",
        "secret_key": "bff77280ca8f445ab7ae3e845afa9e21",
        "nested": {"token": "some_secret_bearer_token", "normal_field": "ok"},
    })
    assert redacted["secret_key"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["normal_field"] == "ok"


def test_ruijie_signature_generation():
    app_id = "test_app"
    secret = "test_secret"
    ts = 1700000000
    params = {"b": "2", "a": "1"}

    sig = rrc._calculate_signature(app_id, secret, ts, params)
    assert isinstance(sig, str)
    assert len(sig) == 32  # MD5 hex length

    # Same inputs must produce deterministic output
    sig2 = rrc._calculate_signature(app_id, secret, ts, params)
    assert sig == sig2


def test_split_ruijie_devices():
    devices = [
        {"devType": "AP", "productModel": "RG-RAP2260(G)", "mac": "00:11:22:33:44:55"},
        {"devType": "Switch", "productModel": "RG-NBS3100-24GT4SFP", "mac": "00:11:22:33:44:56"},
        {"devType": "Gateway", "productModel": "RG-EG210G-E", "mac": "00:11:22:33:44:57"},
        {"productType": "Router", "model": "RG-EW3200GX", "mac": "00:11:22:33:44:58"},
        {"devType": "Unknown", "model": "Custom-Sensor", "mac": "00:11:22:33:44:59"},
    ]

    split = rrc.split_ruijie_devices(devices)
    assert len(split["access_points"]) == 1
    assert len(split["switches"]) == 1
    assert len(split["gateways"]) == 1
    assert len(split["routers"]) == 1
    assert len(split["others"]) == 1
    assert split["access_points"][0]["productModel"] == "RG-RAP2260(G)"
    assert split["gateways"][0]["productModel"] == "RG-EG210G-E"


def test_ruijie_capabilities_read_only_governance():
    caps = rrc.ruijie_api_capabilities()
    assert caps["provider"] == "ruijie_reyee"
    assert "group/list (projects and site hierarchy)" in caps["cloud_api"]["read"]
    assert caps["fabric_integration"]["governance"] == "read_only_default"
    assert caps["fabric_integration"]["public_tools_added"] == 0


def test_device_fabric_provider_registered():
    providers_res = device_fabric.device_fabric_providers()
    assert providers_res.get("ok") is True
    prov_ids = [p["provider_id"] for p in providers_res.get("providers", [])]
    assert "ruijie_reyee" in prov_ids

    # Query via device_fabric_get
    for query in ("ruijie", "reyee", "ruijie_reyee"):
        res = device_fabric.device_fabric_get(query)
        assert res.get("ok") is True
        assert res.get("kind") == "provider"
        assert res["provider"]["provider_id"] == "ruijie_reyee"


def test_device_fabric_fingerprint_ruijie():
    fp = device_fabric._fingerprint(
        "192.168.10.1",
        [80, 443],
        {"http": {"body_snippet": "Welcome to Ruijie Reyee Cloud Managed OS"}},
    )
    assert fp["vendor"] == "Ruijie"
    assert "ruijie_reyee" in fp["provider_ids"]


def test_mocked_network_snapshot():
    mock_creds = rrc.RuijieCredentials(
        base_url="https://cloud.ruijienetworks.com",
        app_id="mock_app",
        secret_key="mock_secret",
        source="test",
    )

    with patch.object(rrc, "get_access_token", return_value=("mock_token", {"ok": True})), \
         patch.object(rrc, "list_projects", return_value={"ok": True, "count": 1, "items": [{"id": "p1", "name": "Bellini"}]}), \
         patch.object(rrc, "list_devices", return_value={"ok": True, "count": 2, "items": [
             {"devType": "AP", "productModel": "RG-RAP2260"},
             {"devType": "Gateway", "productModel": "RG-EG210G"}
         ]}), \
         patch.object(rrc, "list_clients", return_value={"ok": True, "count": 10, "items": []}), \
         patch.object(rrc, "list_alarms", return_value={"ok": True, "count": 0, "items": []}):

        snap = rrc.fetch_full_network_snapshot(project_id="p1", creds=mock_creds)
        assert snap.get("ok") is True
        assert snap.get("provider") == "ruijie_reyee"
        assert snap["projects"]["count"] == 1
        assert snap["devices"]["access_points"]["count"] == 1
        assert snap["devices"]["gateways"]["count"] == 1
        assert snap["credentials"]["secret_configured"] is True
