from __future__ import annotations

import concurrent.futures
from unittest.mock import MagicMock, patch

from inneros_core_runtime import capability_router, coordination_ingest, mcp_diagnostics, mcp_profiles
from inneros_core_runtime import durable_coordination_spine as spine


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


def test_create_agent_message_task_surface_reaches_temporal():
    from inneros_core_runtime.mcp_server import create_agent_message

    captured: list[dict] = []

    def fake_start(task: dict) -> dict:
        captured.append(task)
        return {"ok": True, "workflow_id": task["workflow_id"], "run_id": "run-mcp-surface"}

    with (
        patch(
            "raphiia_openai.memory.agent_messages.create_agent_message",
            return_value={
                "ok": True,
                "created": True,
                "message_id": "msg_mcp_surface",
                "correlation_id": "corr-mcp-surface",
            },
        ),
        patch.object(
            coordination_ingest.mongo_store,
            "get_db",
            return_value={coordination_ingest.COL_AGENT_MESSAGES: MagicMock()},
        ),
        patch.object(spine, "start_task_workflow", side_effect=fake_start),
        patch.object(coordination_ingest.coordination_live, "_publish_task_event", return_value={"ok": True}),
        patch.object(coordination_ingest.coordination_live, "bump_revision", return_value={"ok": True}),
    ):
        result = create_agent_message(
            from_agent="CURSOR",
            target_agent="qwen-coding",
            title="[P0] MCP surface task",
            body="repo: Rafa-Innerchispa/innerops-agentic-platform\n- temporal admission",
            message_type="task",
            idempotency_key="message:msg_mcp_surface",
        )

    assert result["ok"] is True
    assert result["normalization"]["run_id"] == "run-mcp-surface"
    assert captured[0]["source_message_id"] == "msg_mcp_surface"
