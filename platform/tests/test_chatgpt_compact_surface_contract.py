"""chatgpt_compact must expose 25 registered tools including capability_* and device_fabric RO."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import mcp_profiles


def _registered_mcp_tool_names() -> set[str]:
    source = (PLATFORM_DIR / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            is_tool = (
                (isinstance(dec, ast.Attribute) and dec.attr == "tool")
                or (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "tool"
                )
            )
            if is_tool:
                names.add(node.name)
    return names


def test_chatgpt_compact_profile_has_twenty_five_tools() -> None:
    profile = mcp_profiles.get_profile("chatgpt_compact")
    assert profile["ok"] is True
    tools = profile["tools"]
    assert len(tools) == 25
    assert len(tools) <= profile["max_tools"]


def test_chatgpt_compact_includes_capability_gateway_tools() -> None:
    tools = set(mcp_profiles.PROFILES["chatgpt_compact"]["tools"])
    for name in (
        "capability_search",
        "capability_describe",
        "capability_invoke",
        "capability_execution",
    ):
        assert name in tools


def test_chatgpt_compact_tools_are_registered_in_mcp_server() -> None:
    registered = _registered_mcp_tool_names()
    profile_tools = set(mcp_profiles.PROFILES["chatgpt_compact"]["tools"])
    missing = sorted(profile_tools - registered)
    assert not missing, f"profile tools not registered in mcp_server: {missing}"


def test_validate_profiles_passes() -> None:
    result = mcp_profiles.validate_profiles()
    assert result["ok"] is True, result.get("errors")
