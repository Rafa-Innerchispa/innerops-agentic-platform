from unittest import mock

from inneros_core_runtime import ruijie_reyee_client as rj
from inneros_core_runtime import ruijie_reyee_network_ops as rj_ops


def test_ruijie_intent_detection():
    assert rj_ops.is_ruijie_reyee_request("integrar antenas Reyee en bellini")
    assert rj_ops.is_ruijie_reyee_request("switch ruijie easy-smart")
    assert not rj_ops.is_ruijie_reyee_request("wifi unifi casa")


def test_network_ops_without_cloud_creds_still_ok():
    with mock.patch.object(rj, "load_ruijie_credentials", return_value=(None, "ruijie_cloud_credentials_missing")):
        out = rj_ops.ruijie_reyee_network_ops("reyee bellini")
    assert out.get("ok") is True
    assert out.get("mode") == "ruijie_reyee_network_ops"
    assert out.get("limitations")


def test_reyee_capabilities_documentation():
    caps = rj.reyee_api_capabilities()
    assert caps.get("provider") == "ruijie_reyee"
    assert "maint/devices" in str(caps)
