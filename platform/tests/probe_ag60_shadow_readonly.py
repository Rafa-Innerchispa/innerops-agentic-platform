"""Opt-in AG-60 shadow canary: exercise BRANCH dashboard with live READS.

Explicit-only; not selected by routine pytest or GitHub Actions.
No active services are restarted or mutated. Any probe/sweep attempt fails.
Mongo is wrapped to expose only allowed find / find_one calls; the GWN
inventory path is the existing live read-only provider.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _branch_module(fullname, filename):
    path = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / filename
    spec = importlib.util.spec_from_file_location(fullname, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


class _ReadOnlyCollection:
    def __init__(self, original):
        self.original = original

    def find(self, *args, **kwargs):
        return self.original.find(*args, **kwargs)

    def find_one(self, *args, **kwargs):
        return self.original.find_one(*args, **kwargs)


class _ReadOnlyDb:
    def __init__(self, original):
        self.bellini_guardian_state = _ReadOnlyCollection(original.bellini_guardian_state)
        self.bellini_telemetry = _ReadOnlyCollection(original.bellini_telemetry)
        self.bellini_incidents = _ReadOnlyCollection(original.bellini_incidents)


def _forbidden(*args, **kwargs):
    raise AssertionError("Shadow canary forbids active network probes or mutations")


def test_shadow_dashboard_uses_real_mongo_and_cloud_read_only(monkeypatch):
    _branch_module("inneros_core_runtime.ag60_causal_diagnostics",
                   "ag60_causal_diagnostics.py")
    _branch_module("inneros_core_runtime.ag60_source_reconciliation",
                   "ag60_source_reconciliation.py")
    guardian = _branch_module("ag60_branch_guardian_shadow", "bellini_network_guardian.py")

    real_db = guardian.get_mongo_db()
    assert real_db is not None, "MongoDB not available on local runner"
    existing = real_db.bellini_guardian_state.find_one(
        {"site_id": guardian.SITE_ID}, {"_id": 0, "timestamp": 1}
    )
    assert existing and existing.get("timestamp"), "No current existing sample: refusing fallback"
    monkeypatch.setattr(guardian, "get_mongo_db", lambda: _ReadOnlyDb(real_db))
    monkeypatch.setattr(guardian, "get_guardian", _forbidden)
    monkeypatch.setattr(guardian, "probe_icmp", _forbidden)
    monkeypatch.setattr(guardian, "probe_tcp", _forbidden)
    monkeypatch.setattr(guardian, "probe_tailscale", _forbidden)

    dashboard = guardian.bellini_guardian_dashboard()
    diagnosis = dashboard.get("diagnostics") or {}
    proof = dashboard.get("mongo_sample_evidence") or {}
    cloud = dashboard.get("source_reconciliation") or {}
    assert dashboard.get("ok") is True
    assert diagnosis.get("status") == "CURRENT", diagnosis.get("status")
    assert diagnosis.get("root_cause_verified") is False
    assert proof.get("two_recent_distinct_samples") is True, proof.get("status")
    assert len(proof.get("samples") or []) >= 2
    assert cloud.get("status") == "CURRENT", cloud.get("status")
    assert cloud.get("root_cause_verified") is False
    assert cloud.get("mutations_performed") is False
    assert isinstance(cloud.get("comparisons"), list)
    out = {
        "guardian_sample": diagnosis.get("timestamp"),
        "diagnosis_status": diagnosis.get("status"),
        "offline_count": diagnosis.get("offline_count"),
        "mongo_proof_status": proof.get("status"),
        "mongo_sample_ids_and_times": [
            {"id": x.get("id"), "timestamp": x.get("timestamp")}
            for x in proof.get("samples", [])[:2]
        ],
        "cloud_snapshot_status": cloud.get("status"),
        "cloud_devices_compared": cloud.get("cloud_devices"),
        "cloud_accesspoints_not_monitored": cloud.get("unmonitored_cloud_aps"),
        "ip_only_matches": sum(1 for x in cloud["comparisons"]
                              if x.get("identity_match") == "IP_ONLY_UNVERIFIED"),
        "physical_root_cause_verified": False,
        "network_mutations": False,
        "production_deployed": False,
    }
    print("AG60_BRANCH_SHADOW_CANARY=" + json.dumps(out, sort_keys=True))
