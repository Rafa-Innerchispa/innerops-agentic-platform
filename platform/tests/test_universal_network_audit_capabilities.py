"""Universal network audit capabilities — registry + read-only invoke (mocked)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime.capability_gateway import capability_describe, capability_invoke, capability_search


def test_capability_search_finds_universal_network_audit():
    import inneros_core_runtime.capability_gateway  # noqa: F401
    res = capability_search(query="network audit ports segmentation dhcp", max_results=20)
    assert res["ok"] is True
    ids = {c["capability_id"] for c in res["capabilities"]}
    assert "network.device.ports.v1" in ids
    assert "network.dhcp.arp.v1" in ids


def test_ports_capability_read_only(monkeypatch):
    import inneros_core_runtime.capability_gateway  # noqa: F401
    monkeypatch.setattr(
        "inneros_core_runtime.universal_network_audit._resolve_gwn",
        lambda t, s: {"creds": None, "credentials_error": "mock", "network_id": None, "tenant_row": None},
    )
    monkeypatch.setattr(
        "inneros_core_runtime.device_fabric.device_fabric_inventory",
        lambda **kw: {"ok": True, "inventory": [{"ip": "192.168.3.1", "vendor": "Grandstream"}]},
    )
    res = capability_invoke(
        "network.device.ports.v1",
        {"tenant_id": "bellini", "site_id": "bellini-i-ii"},
    )
    assert res["ok"] is True
    assert res["result"]["mode"] == "read_only"
    assert res["result"]["data"]["count"] >= 1


def test_all_four_manifests_are_read_only():
    for cap_id in (
        "network.device.ports.v1",
        "network.l2.topology.v1",
        "network.segmentation.audit.v1",
        "network.dhcp.arp.v1",
    ):
        desc = capability_describe(cap_id)
        assert desc["ok"] is True
        assert desc["capability"]["mode"] == "read_only"
