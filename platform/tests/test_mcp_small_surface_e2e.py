from __future__ import annotations

import concurrent.futures

from inneros_core_runtime import capability_router, mcp_diagnostics, mcp_profiles


def test_route_mcp_tools_accepts_extra_mcp_layer_kwargs():
    """Runtime must tolerate MCP-layer kwargs (e.g. for_model) on older deploy siblings."""
    result = capability_router.route_tools(
        title="surface e2e",
        requested_profile="chatgpt_compact",
        granted_scopes=["ralfia:read", "ralfia:write"],
        max_risk="medium",
        for_model="small",
        max_tools=25,
        unexpected_future_field=True,
    )
    assert result["ok"] is True
    assert "capability_search" in result["tools"]


def test_route_mcp_tools_via_mcp_server_wrapper():
    from inneros_core_runtime.mcp_server import route_mcp_tools

    result = route_mcp_tools(
        title="mcp wrapper e2e",
        requested_profile="chatgpt_compact",
        granted_scopes=["ralfia:read"],
        max_risk="low",
        for_model="small",
    )
    assert result["ok"] is True
    assert result["profile"] == "chatgpt_compact"
    assert result["tool_count"] <= 25


def test_batch_read_only_small_tools_do_not_raise():
    profile = mcp_profiles.get_profile("chatgpt_compact")
    pin = profile["profile_pin"]

    def _one_call(_: int) -> dict:
        return mcp_diagnostics.diagnose_mcp_session(
            client_tool_count=profile["tool_count"],
            client_profile_pin=pin,
            client_catalog_version=mcp_profiles.PROFILES_VERSION,
            profile="chatgpt_compact",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_one_call, range(12)))

    assert len(results) == 12
    assert all(item.get("session_valid") for item in results)
