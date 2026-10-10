"""Fail-closed two-node MCP routing when primary or secondary is unavailable."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "mcp_fleet.py"
SPEC = importlib.util.spec_from_file_location("candidate_mcp_fleet_ha", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fleet)


@pytest.fixture(autouse=True)
def mocked_fleet(monkeypatch):
    monkeypatch.setattr(fleet, "runtime_fingerprints", lambda: {
        "runtime_consistent": True, "divergences": [], "files": []
    })


def _probes(intel, amd):
    return lambda node, force=False: {
        "node": node,
        "ok": intel if node == "intel" else amd,
        "tcp_ok": intel if node == "intel" else amd,
        "mcp_ok": intel if node == "intel" else amd,
    }


def test_intel_unavailable_amd_remains_eligible(monkeypatch):
    monkeypatch.setattr(fleet, "probe_node", _probes(False, True))
    urls = fleet.get_mcp_urls_ordered(preferred_node="intel", active_only=True)
    assert urls == [fleet._mcp_url(fleet.AMD_HOST)]
    assert fleet.resolve_mcp_url("business_status") == urls[0]
    status = fleet.fleet_status()
    assert status["ok"] is False
    assert status["serviceable"] is True
    assert status["availability"] == "degraded"
    assert status["healthy_nodes"] == ["amd"]
    assert status["stateful_failover_certified"] is False


def test_amd_unavailable_intel_remains_eligible(monkeypatch):
    monkeypatch.setattr(fleet, "probe_node", _probes(True, False))
    urls = fleet.get_mcp_urls_ordered(preferred_node="amd", active_only=True)
    assert urls == [fleet._mcp_url(fleet.INTEL_HOST)]
    assert fleet.resolve_mcp_url("ha_list_entities") == urls[0]
    status = fleet.fleet_status()
    assert status["serviceable"] is True
    assert status["availability"] == "degraded"
    assert status["healthy_nodes"] == ["intel"]


def test_both_nodes_down_returns_no_fake_healthy_endpoint(monkeypatch):
    monkeypatch.setattr(fleet, "probe_node", _probes(False, False))
    assert fleet.get_mcp_urls_ordered(active_only=True) == []
    assert fleet.resolve_mcp_url("ha_list_entities") == ""
    status = fleet.fleet_status()
    assert status["ok"] is False
    assert status["serviceable"] is False
    assert status["availability"] == "down"


def test_both_healthy_and_parity_verified(monkeypatch):
    monkeypatch.setattr(fleet, "probe_node", _probes(True, True))
    status = fleet.fleet_status()
    assert status["ok"] is True
    assert status["availability"] == "healthy"
    assert set(status["healthy_nodes"]) == {"intel", "amd"}
    assert status["stateful_failover_certified"] is False


def test_version_mismatch_is_degraded_not_silent_success(monkeypatch):
    monkeypatch.setattr(fleet, "probe_node", _probes(True, True))
    monkeypatch.setattr(fleet, "runtime_fingerprints", lambda: {
        "runtime_consistent": False, "divergences": [{"file": "mcp_fleet.py"}], "files": []
    })
    status = fleet.fleet_status()
    assert status["ok"] is False
    assert status["serviceable"] is True
    assert status["availability"] == "degraded"
