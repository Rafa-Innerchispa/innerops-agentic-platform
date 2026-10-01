from __future__ import annotations

from raphiia_openai.mcp_catalog import tool_catalog

from inneros_core_runtime import mcp_diagnostics, mcp_profiles


def test_chatgpt_compact_23_of_23_passes_without_global_stale():
    profile = mcp_profiles.get_profile("chatgpt_compact")
    assert profile["ok"] is True
    pin = profile["profile_pin"]
    expected_count = profile["tool_count"]

    result = mcp_diagnostics.diagnose_mcp_session(
        client_tool_count=expected_count,
        client_catalog_version=mcp_profiles.PROFILES_VERSION,
        client_profile_pin=pin,
        profile="chatgpt_compact",
    )

    assert result["session_valid"] is True
    assert result["stale_catalog"] is False
    assert result["likely_issue"] == "profile_ok"
    assert result["needs_refresh_connector"] is False
    assert result["expected_tool_count"] == expected_count
    assert result["diagnosis_mode"] == "profile"
    assert result["catalog_guard"]["status"] == "profile_projection"
    assert result["global_catalog_guard"] is not None
    assert result["server_snapshot"]["public_url"].endswith("/router/mcp")


def test_global_tool_count_on_small_profile_is_hint_not_automatic_stale():
    profile = mcp_profiles.get_profile("chatgpt_compact")
    global_count = len(tool_catalog.ALL_MCP_TOOL_NAMES)
    result = mcp_diagnostics.diagnose_mcp_session(
        client_tool_count=global_count,
        client_catalog_version=mcp_diagnostics.CATALOG_VERSION,
        profile="chatgpt_compact",
        client_profile_pin=profile["profile_pin"],
    )
    assert result["session_valid"] is False
    assert result["stale_catalog"] is False
    assert "client_tool_count_mismatch" in result["reasons"]
    assert "client_reports_global_tool_count_use_profile_projection" in result["hints"]


def test_unknown_profile_marks_invalid():
    result = mcp_diagnostics.diagnose_mcp_session(profile="not_a_real_profile", client_tool_count=23)
    assert result["session_valid"] is False
    assert "unknown_profile" in result["reasons"]
