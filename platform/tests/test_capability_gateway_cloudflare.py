"""Regression tests: Cloudflare reads exposed through MCP Small Capability Gateway.

All Cloudflare HTTP/Vault interactions are mocked. No real tokens or DNS writes.
"""
from __future__ import annotations

import urllib.parse
from types import SimpleNamespace

import pytest

from inneros_core_runtime import capability_gateway as gw
from inneros_core_runtime import capability_gateway_cloudflare as cf


@pytest.fixture(autouse=True)
def register_capabilities():
    cf.register_cloudflare_read_capabilities()


@pytest.fixture
def fake_ag(monkeypatch):
    requests = []
    names = {"pcdoctor.ai": "cloudflare_pcdoctor_ai", "innerchispa.us": "cloudflare_pcdoctor_ai"}

    def zone_validate(zone):
        name = (zone or "pcdoctor.ai").strip().lower()
        if name not in names:
            raise ValueError("zone_not_allowlisted:" + name)
        return name

    def creds(zone_name="pcdoctor.ai"):
        zone_validate(zone_name)
        return {"account_id": "private_account_id", "token": "private_api_token"}

    def zone(name, *, creds):
        return {"name": name, "status": "active", "id": "private_zone_id"}

    def request(method, path, *, creds):
        assert method == "GET", "Cloudflare capability must never mutate"
        requests.append((method, path))
        if "/dns_records" in path:
            return {"success": True, "result_info": {"total_count": 7}}
        if path.startswith("/zones?"):
            page = int(urllib.parse.parse_qs(path.partition("?")[2])["page"][0])
            if page == 1:
                return {
                    "success": True,
                    "result": [
                        {"name": "pcdoctor.ai", "status": "active", "name_servers": ["ns1.cloudflare.com"]},
                        {"name": "not-in-allowlist.example", "status": "active"},
                    ],
                    "result_info": {"total_pages": 2},
                }
            return {
                "success": True,
                "result": [{"name": "innerchispa.us", "status": "pending"}],
                "result_info": {"total_pages": 2},
            }
        raise AssertionError("Unexpected endpoint: " + path)

    fake = SimpleNamespace(
        CF_DEFAULT_ZONE="pcdoctor.ai",
        CF_ZONE_VAULT_CATEGORIES=names,
        _validate_zone=zone_validate,
        _validate_hostname=lambda name, zone: name,
        _cloudflare_credentials=creds,
        _get_zone=zone,
        _cf_request=request,
        cloudflare_tunnel_ingress_status=lambda hostname, config_path="": {
            "ok": True,
            "count": 1,
            "matches": [{
                "hostname": hostname,
                "service": "http://127.0.0.1:8000",
                "config_path": "/home/rlopez/.cloudflared/private.yml",
                "tunnel": "private_tunnel_id",
            }],
        },
    )
    monkeypatch.setattr(cf, "_backend", lambda: fake)
    return fake, requests


def test_gateway_search_describe_and_legacy_alias():
    match = gw.capability_search(query="cloudflare")
    ids = {c["capability_id"] for c in match["capabilities"]}
    assert {"cloudflare.zone.status.read.v1", "cloudflare.zones.inventory.read.v1",
            "cloudflare.tunnel.status.read.v1"} <= ids
    for cid in ids:
        manifest = gw.capability_describe(cid)["capability"]
        assert manifest["mode"] == "read_only"
        assert manifest["required_scopes"] == ["ralfia:read"]
    assert gw.capability_describe("cloudflare_status")["ok"] is True
    assert gw.capability_describe("cloudflare_dns_upsert")["ok"] is False


def test_zone_status_is_redacted_and_read_only(fake_ag):
    result = gw.capability_invoke(
        "cloudflare_status", {"zone_name": "pcdoctor.ai"}, context={"enforce_read_only": True}
    )
    assert result["ok"] and result["result"]["zone"] == {
        "name": "pcdoctor.ai", "status": "active"
    }
    assert result["result"]["dns_record_count"] == 7
    assert result["result"]["permissions"] == {"zone_read": True, "dns_read": True}
    data = repr(result)
    assert "private_api_token" not in data
    assert "private_account_id" not in data
    assert "private_zone_id" not in data


def test_rejects_arbitrary_zone_before_using_vault(fake_ag):
    result = gw.capability_invoke(
        "cloudflare.zone.status.read.v1", {"zone_name": "unowned.example"}
    )
    assert result["ok"] is False
    assert result["result"]["error"] == "ZONE_NOT_ALLOWLISTED"
    assert fake_ag[1] == []


def test_paginated_inventory_filters_non_allowlisted_zones(fake_ag):
    result = gw.capability_invoke(
        "cloudflare.zones.inventory.read.v1", {}, context={"enforce_read_only": True}
    )
    assert result["ok"], result
    data = result["result"]
    assert data["scope"] == "ag44_allowlisted_zones_only"
    assert data["complete_account_inventory"] is False
    assert data["visible_count"] == 2
    assert [x["name"] for x in data["zones"]] == ["innerchispa.us", "pcdoctor.ai"]
    raw = repr(result)
    for excluded in ("not-in-allowlist", "private_account_id", "private_api_token"):
        assert excluded not in raw
    assert len(fake_ag[1]) == 2


def test_tunnel_scrubs_internal_paths_and_service_addresses(fake_ag):
    result = gw.capability_invoke(
        "cloudflare_tunnel_ingress_status", {"hostname": "mcp.pcdoctor.ai"}
    )
    assert result["ok"] is True
    data = result["result"]
    assert data == {
        "ok": True, "read_only": True, "hostname": "mcp.pcdoctor.ai",
        "configured": True, "ingress_rule_count": 1,
    }
    assert "127.0.0.1" not in repr(result)
    assert "/home/" not in repr(result)
    assert "private_tunnel_id" not in repr(result)


def test_permission_error_cannot_leak_raw_backend_error(fake_ag, monkeypatch):
    backend = fake_ag[0]

    def fail(method, path, *, creds):
        raise RuntimeError("cloudflare_api_http_403: private_api_token=SHOULD_NEVER_LEAK")

    backend._cf_request = fail
    result = gw.capability_invoke("cloudflare.zones.inventory.read.v1", {})
    assert not result["ok"]
    assert result["result"]["error"] == "CLOUDFLARE_PERMISSION_DENIED"
    assert "SHOULD_NEVER_LEAK" not in repr(result)
