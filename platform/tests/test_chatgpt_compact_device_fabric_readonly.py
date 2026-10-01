"""chatgpt_compact must expose read-only Device Fabric inventory/discover for Bellini."""

from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import mcp_profiles
from inneros_core_runtime.auth_middleware import _token_profile_guard


def test_chatgpt_compact_includes_device_fabric_readonly_tools() -> None:
    profile = mcp_profiles.get_profile("chatgpt_compact")
    assert profile["ok"] is True
    tools = set(profile["tools"])
    for name in (
        "device_fabric_health",
        "device_fabric_get",
        "device_fabric_inventory",
        "device_fabric_discover",
        "device_fabric_providers",
    ):
        assert name in tools, f"missing {name} in chatgpt_compact"
    assert len(tools) <= 25


def test_profile_guard_allows_device_fabric_inventory_and_discover() -> None:
    token = {"mcp_profile": "chatgpt_compact"}
    for tool in ("device_fabric_inventory", "device_fabric_discover"):
        guard = _token_profile_guard(token, tool)
        assert guard["ok"] is True, guard


def test_profile_guard_still_blocks_device_fabric_bind() -> None:
    token = {"mcp_profile": "chatgpt_compact"}
    guard = _token_profile_guard(token, "device_fabric_bind")
    assert guard["ok"] is False
    assert guard["error"] == "tool_not_allowed_for_profile"
