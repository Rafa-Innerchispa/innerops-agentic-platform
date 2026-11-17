"""Unit tests for Windows <-> InnerOS <-> Kiro Autonomous Bridge capabilities."""

from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import capability_gateway
from inneros_core_runtime import capability_gateway_windows as wgw


def test_windows_capabilities_registered():
    res = capability_gateway.capability_search("windows")
    ids = {c["capability_id"] for c in res.get("capabilities", [])}
    expected = {
        "windows.status.v1",
        "windows.kiro.status.v1",
        "windows.kiro.sessions.v1",
        "windows.workspace.status.v1",
        "windows.tests.results.v1",
        "windows.bridge.health.v1",
        "windows.bridge.dispatch.v1",
        "windows.bridge.receipt.v1",
    }
    assert expected.issubset(ids)


def test_freshness_helper():
    fresh, age = wgw._freshness(wgw._utc_iso())
    assert fresh is True
    assert age is not None and age < 5.0
    stale, _ = wgw._freshness("2020-01-01T00:00:00+00:00")
    assert stale is False


if __name__ == "__main__":
    test_windows_capabilities_registered()
    test_freshness_helper()
    print("UNIT_CHECKS_PASS")
