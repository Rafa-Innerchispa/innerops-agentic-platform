import importlib.util
from pathlib import Path
from unittest import mock

import pytest

from inneros_core_runtime import grandstream_gwn_client as gwn
from inneros_core_runtime import grandstream_gwn_network_ops as gwn_ops

MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "homeassistant_client.py"
SPEC = importlib.util.spec_from_file_location("ag32_homeassistant_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
ha = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ha)


def test_grandstream_intent_routing_beats_generic_home_ops():
    with mock.patch.object(gwn_ops, "grandstream_gwn_network_ops", return_value={"ok": True, "mode": "grandstream_gwn_network_ops"}):
        out = ha.run_home_ops_cycle("optimiza wifi GWN en Bellini")
    assert out.get("mode") == "grandstream_gwn_network_ops"
    assert out.get("entrypoint") == "grandstream_gwn_network_ops.grandstream_gwn_network_ops"


def test_unifi_still_routes_when_explicit():
    with mock.patch.object(ha, "unifi_network_ops", return_value={"ok": True, "mode": "unifi_network_ops"}):
        out = ha.run_home_ops_cycle("revisa el wifi unifi lento")
    assert out.get("mode") == "unifi_network_ops"


def test_grandstream_ops_without_cloud_creds_returns_mongo_evidence():
    with mock.patch.object(gwn, "load_gwn_credentials", return_value=(None, "gwn_cloud_credentials_missing")):
        out = gwn_ops.grandstream_gwn_network_ops("revisa red grandstream bellini")
    assert out.get("ok") is True
    assert out.get("client_id") == "bellini"
    assert out["evidence"]["mongo_inventory"].get("ok") is True
    assert any("credentials" in lim.lower() or "GWN_CLOUD" in lim for lim in out.get("limitations", []))


def test_gwn_signature_query_format():
    query, body, _ts = gwn._sign_request("tok123", "app99", "secret", {"networkId": 1})
    assert "access_token=tok123" in query
    assert "appID=app99" in query
    assert "signature=" in query
    assert '"networkId":1' in body


def test_ssid_update_fail_closed_without_approval():
    creds = gwn.GwnCredentials(base_url="https://www.gwn.cloud", app_id="1", secret_key="x", source="test")
    out = gwn.ssid_update(creds, {"networkId": 1, "id": 2}, dry_run=True, owner_approval_ref="")
    assert out.get("dry_run") is True
    assert out.get("owner_approval_required") is True
