"""Offline contract tests loading the branch files, not an installed InnerOS copy."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import pytest
from inneros_core_runtime import device_fabric


def _local_module(name, filename):
    path = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bng(monkeypatch):
    diagnostics = _local_module("inneros_core_runtime.ag60_causal_diagnostics",
                                "ag60_causal_diagnostics.py")
    monkeypatch.setitem(sys.modules, "inneros_core_runtime.ag60_causal_diagnostics", diagnostics)
    # CI intentionally installs only minimal offline test requirements.
    # Stub the unused Mongo import, never connect to a database.
    if "pymongo" not in sys.modules:
        from types import ModuleType
        stub = ModuleType("pymongo")
        stub.database = ModuleType("pymongo.database")
        monkeypatch.setitem(sys.modules, "pymongo", stub)
    return _local_module("bellini_network_guardian_under_test", "bellini_network_guardian.py")


class _State:
    def find_one(self, *_args, **_kwargs):
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "site_id": "bellini-i-ii",
            "targets": [
                {"asset_id": "bellini_switch_185", "ip": "192.168.3.185",
                 "online": False, "icmp": {"loss_pct": 100}},
                {"asset_id": "bellini_ap_213", "ip": "192.168.3.213",
                 "online": False, "icmp": {"loss_pct": 100}},
            ],
            "summary": {"offline_count": 2},
        }


class _DB:
    bellini_guardian_state = _State()


def test_existing_mcp_status_is_enriched_without_extra_probes(monkeypatch, bng):
    monkeypatch.setattr(bng, "get_mongo_db", lambda: _DB())
    monkeypatch.setattr(device_fabric, "device_fabric_inventory", lambda **kwargs: {
        "inventory": [{"asset_id": "bellini_switch_185", "device_name": "Switch Administración",
                       "device_type": "poe_switch", "vendor": "Hikvision",
                       "model": "DS-3E1510P-EI/M"}]})
    status = bng.bellini_guardian_status()
    assert status["source"] == "mongodb_guardian_state"
    diag = status["diagnostics"]
    assert diag["status"] == "CURRENT"
    assert diag["root_cause_verified"] is False
    assert diag["offline_count"] == 2
    switch, ap = diag["incidents"]
    assert switch["vendor"] == "Hikvision"
    assert switch["model"] == "DS-3E1510P-EI/M"
    assert ap["upstream"] == "SW_T1_P0"
    assert not ap["relationship_verified"]
    assert ap["floor"] == "ubicación no identificada"


def test_dashboard_exposes_diagnostics_without_fake_root_cause(monkeypatch, bng):
    monkeypatch.setattr(bng, "get_mongo_db", lambda: None)
    monkeypatch.setattr(bng, "bellini_guardian_status", lambda: {
        "summary": {"offline_count": 1}, "targets": [],
        "diagnostics": {"status": "STALE", "root_cause_verified": False}})
    dash = bng.bellini_guardian_dashboard()
    assert dash["diagnostics"]["root_cause_verified"] is False
    assert dash["diagnostics"]["status"] == "STALE"


def test_inventory_failure_fails_closed(monkeypatch, bng):
    def broken(**kwargs):
        raise RuntimeError("down")
    monkeypatch.setattr(device_fabric, "device_fabric_inventory", broken)
    status = bng._enrich_guardian_status({"timestamp": "2026-10-19T00:00:00Z", "targets": []})
    assert status["diagnostics"]["status"] == "UNAVAILABLE"
    assert status["diagnostics"]["root_cause_verified"] is False


def test_root_cause_is_never_declared_by_icmp(monkeypatch, bng):
    monkeypatch.setattr(bng, "get_mongo_db", lambda: None)
    sample = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gateway_online": False, "gateway_rtt_ms": 0.0, "tailscale": {},
        "summary": {"offline_count": 1},
        "targets": [{"ip": "192.168.3.1", "asset_id": "gw",
                     "device_type": "gateway", "online": False}],
    }
    guardian = bng.BelliniNetworkGuardian()
    guardian._analyze_incidents(sample)
    incident = guardian.active_incident
    assert incident["trigger"] == "GATEWAY_UNREACHABLE"
    assert incident["root_cause_candidate"] == "GATEWAY_NO_RESPONSE_CAUSE_UNKNOWN"
    assert incident["confidence"] is None
    assert incident["root_cause_verified"] is False
    assert incident["first_failed_component"] == "unknown"


def test_multiple_aps_do_not_imply_poe_outage(monkeypatch, bng):
    monkeypatch.setattr(bng, "get_mongo_db", lambda: None)
    sample = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gateway_online": True, "gateway_rtt_ms": 10.0,
        "tailscale": {"derp": False}, "summary": {"offline_count": 2},
        "targets": [
            {"ip": "192.168.3.1", "asset_id": "gw", "device_type": "gateway", "online": True},
            {"ip": "192.168.3.188", "asset_id": "ap188", "device_type": "ap", "online": False},
            {"ip": "192.168.3.213", "asset_id": "ap213", "device_type": "ap", "online": False},
        ],
    }
    guardian = bng.BelliniNetworkGuardian()
    guardian._analyze_incidents(sample)
    incident = guardian.active_incident
    assert incident["trigger"] == "MULTIPLE_AP_OUTAGE"
    assert incident["root_cause_candidate"] == "MULTIPLE_AP_NO_REPLY_CAUSE_UNKNOWN"
    assert incident["confidence_qualifier"] == "unverified_not_calibrated"
    assert incident["root_cause_verified"] is False
