from __future__ import annotations
import pytest
from inneros_core_runtime.capability_gateway import capability_search, capability_describe, capability_invoke


def test_cpanel_capability_search_matches():
    res_cpanel = capability_search("cpanel")
    assert res_cpanel["ok"] is True
    ids = [c["capability_id"] for c in res_cpanel["capabilities"]]
    assert "hosting.cpanel.query.v1" in ids
    assert "hosting.cpanel.mutate.v1" in ids

    res_wp = capability_search("wordpress")
    assert res_wp["ok"] is True
    assert any("hosting.cpanel" in c["capability_id"] for c in res_wp["capabilities"])

    res_ssh = capability_search("ssh")
    assert res_ssh["ok"] is True
    assert any("hosting.cpanel" in c["capability_id"] for c in res_ssh["capabilities"])


def test_cpanel_capability_describe():
    desc = capability_describe("hosting.cpanel.query.v1")
    assert desc["ok"] is True
    manifest = desc["capability"]
    assert manifest["domain"] == "hosting"
    assert manifest["mode"] == "read_only"
    assert "list_domains" in manifest["parameters_schema"]["properties"]["action"]["enum"]


def test_cpanel_capability_invoke_read_only_live():
    res = capability_invoke("hosting.cpanel.query.v1", {"action": "get_domain_info", "domain": "danzasjazz.com"})
    assert res["ok"] is True
    assert res["status"] == "COMPLETED"
    info = res["result"]["domain_info"]
    assert info["domain"] == "danzasjazz.com"
    assert info["documentroot"] == "/home/pcdoctor/public_html/danzasjazz.com"
    assert info["ip"] == "23.111.160.154"
