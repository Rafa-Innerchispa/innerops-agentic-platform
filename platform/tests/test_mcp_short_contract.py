from __future__ import annotations

import json
from types import SimpleNamespace

from inneros_core_runtime import coordination_docs, local_model_manager, mcp_diagnostics, project_runtime_registry, self_heal_metrics
from inneros_core_runtime.agents import ag52_iskcon_ops_agent
from inneros_core_runtime.mcp_catalog import tool_catalog
from inneros_core_runtime import mcp_profiles

REMOVED_645_TO_609_TOOLS = {
    "agent_iskcon_action",
    "agent_iskcon_artifact_download",
    "agent_iskcon_class_update",
    "agent_iskcon_module_manifest",
    "agent_iskcon_sources",
    "agent_iskcon_yoga_campaign",
    "digitalocean_mi325x_deploy_plan",
    "editorial_image_providers",
    "disk_steward_cleanup_verified",
    "disk_steward_execute_migration",
    "disk_steward_inventory",
    "disk_steward_plan_migration",
    "disk_steward_update_backup_policy",
    "disk_steward_verify_migration",
    "get_disk_steward_status",
    "identify_agent_session",
    "inneros_agent_fabric_status",
    "inneros_dual_deployment_drill",
    "inneros_dual_deployment_status",
    "inneros_dual_queue_operation",
    "inneros_dual_reconcile_operations",
    "inneros_ingest_drop_run",
    "inneros_ingest_drop_status",
    "judge_console_content_get",
    "judge_mi325x_deploy",
    "judge_model_routing_policy",
    "judge_resource_telemetry",
    "judge_safe_trigger",
    "judge_trace_current",
    "judge_trace_detail",
    "judge_trace_history",
    "judge_trace_kpis",
    "judge_trace_record",
    "judge_workflow_continue",
    "judge_workflow_execute",
    "judge_workflow_get",
    "judge_workflow_list",
    "judge_workflow_start",
    "list_self_heal_baselines",
    "list_self_heal_incidents",
    "module_action",
    "module_artifact_download",
    "module_manifest",
    "save_self_heal_baseline",
    "summarize_self_heal_incidents",
}


def test_mcp_diagnostics_survive_partial_catalog_metadata(monkeypatch) -> None:
    original = dict(tool_catalog.TOOL_DEFINITIONS["mcp_version"])
    partial = dict(original)
    partial.pop("reads_from", None)
    partial.pop("writes_to", None)
    monkeypatch.setitem(tool_catalog.TOOL_DEFINITIONS, "mcp_version", partial)

    version = mcp_diagnostics.mcp_version(session_id="test-short")
    capabilities = mcp_diagnostics.list_mcp_capabilities()
    described = mcp_diagnostics.describe_tool("mcp_version")

    assert version["ok"] is True
    assert capabilities["ok"] is True
    assert described["reads_from"] == []
    assert described["writes_to"] == []


def test_project_runtime_bootstrap_schema_exposes_ref_and_sha() -> None:
    schema = tool_catalog.describe_tool("project_runtime_bootstrap")["input_schema"]

    assert schema["base_ref"] == "git ref|null"
    assert schema["expected_sha"] == "git sha|null"


def test_diagnose_mcp_session_uses_profile_expected_tool_count() -> None:
    profile = mcp_profiles.get_profile("chatgpt_compact")
    profile_tools = profile["tools"]

    result = mcp_diagnostics.diagnose_mcp_session(
        client_tool_count=len(profile_tools),
        client_seen_tools=profile_tools,
        profile="chatgpt_compact",
        session_id="short-fresh",
    )

    assert result["profile"] == "chatgpt_compact"
    assert result["expected_tool_count"] == 15
    assert result["global_runtime_tool_count"] >= result["expected_tool_count"]
    assert result["stale_catalog"] is False


def test_diagnose_mcp_session_detects_stale_compact_client_missing_devswarm_tools() -> None:
    stale_tools = [
        "mcp_version",
        "diagnose_mcp_session",
        "list_mcp_tool_profiles",
        "route_mcp_tools",
        "bootstrap_context",
        "get_coordination_live",
        "poll_agent_inbox",
        "list_ops_tasks",
        "create_agent_message",
        "a2a_status",
        "a2a_agent_cards",
        "project_runtime_bootstrap",
    ]

    result = mcp_diagnostics.diagnose_mcp_session(
        client_tool_count=len(stale_tools),
        client_seen_tools=stale_tools,
        profile="chatgpt_compact",
        session_id="short-stale-12",
    )

    assert result["expected_tool_count"] == 15
    assert result["this_client_sees_tools"] == 12
    assert result["stale_catalog"] is True
    assert result["needs_refresh_connector"] is True


def test_catalog_guard_preserves_645_historical_tool_names() -> None:
    previous = {
        "tool_names": sorted(set(tool_catalog.ALL_MCP_TOOL_NAMES) | REMOVED_645_TO_609_TOOLS),
        "tool_names_hash": "baseline-test",
    }

    guard = mcp_diagnostics._catalog_guard(previous)

    assert guard["removed_tools"] == []
    assert guard["tool_loss_detected"] is False
    for name in REMOVED_645_TO_609_TOOLS:
        assert name in tool_catalog.ALL_MCP_TOOL_NAMES
        assert tool_catalog.describe_tool(name)["ok"] is True


def test_removed_backend_compatibility_tools_are_not_silent_success() -> None:
    meta = tool_catalog.describe_tool("inneros_dual_queue_operation")

    assert meta["ok"] is True
    assert meta["output_schema"]["status"] == "NOT_READY_BACKEND_REMOVED"
    assert "fail-closed" in meta["description"]


def test_restored_backend_symbols_exist_without_live_side_effects() -> None:
    assert callable(self_heal_metrics.save_self_heal_baseline)
    assert callable(self_heal_metrics.list_self_heal_incidents)
    assert callable(self_heal_metrics.list_self_heal_baselines)
    assert ag52_iskcon_ops_agent.agent_iskcon_sources()["ok"] is True
    assert ag52_iskcon_ops_agent.agent_iskcon_yoga_campaign(days=1, dry_run=True)["send_status"] == "approval_required_not_sent"
    assert local_model_manager.local_model_runtime_status()["ok"] is True


def test_catalog_guard_requires_owner_approval_for_future_tool_removal() -> None:
    previous = {
        "tool_names": sorted(set(tool_catalog.ALL_MCP_TOOL_NAMES) | {"future_owner_only_tool"}),
        "tool_names_hash": "baseline-test",
    }

    guard = mcp_diagnostics._catalog_guard(previous)

    assert guard["status"] == "tool_loss_detected"
    assert guard["needs_owner_approval"] is True
    assert guard["unapproved_removed_tools"] == ["future_owner_only_tool"]


def test_catalog_guard_respects_explicit_owner_approved_retirement() -> None:
    previous = {
        "tool_names": sorted(set(tool_catalog.ALL_MCP_TOOL_NAMES) | {"retired_by_owner_tool"}),
        "tool_names_hash": "baseline-test",
        "approved_tool_retirements": [{"tool": "retired_by_owner_tool", "approved_by": "RAFAEL"}],
    }

    guard = mcp_diagnostics._catalog_guard(previous)

    assert guard["status"] == "tool_loss_detected"
    assert guard["needs_owner_approval"] is False
    assert guard["unapproved_removed_tools"] == []


def test_project_runtime_bootstrap_passes_ref_and_sha_to_node_helper(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(project_runtime_registry, "_core_root", lambda: tmp_path)
    project_runtime_registry.register_project(
        "innerops-agentic-platform",
        "Rafa-Innerchispa/innerops-agentic-platform",
        str(tmp_path / "workspaces" / "innerops-agentic-platform"),
        actor="test",
    )

    expected_sha = "a" * 40

    def fake_run_node(node, args, *, input_text="", timeout=120):
        captured["payload"] = json.loads(input_text)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "observed_sha": expected_sha}), stderr="")

    monkeypatch.setattr(project_runtime_registry, "_run_node", fake_run_node)

    result = project_runtime_registry.bootstrap_runtime(
        node="primary",
        project_id="innerops-agentic-platform",
        repo="Rafa-Innerchispa/innerops-agentic-platform",
        base_ref="main",
        expected_sha=expected_sha,
        dry_run=False,
    )

    assert result["ok"] is True
    assert captured["payload"]["base_ref"] == "main"
    assert captured["payload"]["expected_sha"] == expected_sha


def test_project_runtime_bootstrap_helper_mismatch_fails_closed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(project_runtime_registry, "_core_root", lambda: tmp_path)
    project_runtime_registry.register_project(
        "innerops-agentic-platform",
        "Rafa-Innerchispa/innerops-agentic-platform",
        str(tmp_path / "workspaces" / "innerops-agentic-platform"),
        actor="test",
    )

    expected_sha = "a" * 40

    def fake_run_node(node, args, *, input_text="", timeout=120):
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({"ok": False, "error": "expected_sha_mismatch", "observed_sha": "b" * 40}),
            stderr="",
        )

    monkeypatch.setattr(project_runtime_registry, "_run_node", fake_run_node)

    result = project_runtime_registry.bootstrap_runtime(
        node="primary",
        project_id="innerops-agentic-platform",
        repo="Rafa-Innerchispa/innerops-agentic-platform",
        base_ref="main",
        expected_sha=expected_sha,
        dry_run=False,
    )

    assert result["ok"] is False
    assert result["result"]["error"] == "expected_sha_mismatch"


def test_bootstrap_context_uses_live_runtime_banner_and_filters_stale_lines(monkeypatch) -> None:
    monkeypatch.setattr(
        coordination_docs,
        "_bootstrap_context_legacy",
        lambda: {
            "ok": True,
            "content": "- Runtime vivo: 2.23.0 / 117 tools.\n- Keep useful context.",
            "project_map": {"central_map": "- Ralphi-IA-MCP quedó en 2.23.0 / 117 tools."},
        },
    )
    monkeypatch.setattr(coordination_docs, "read_coordination_file", lambda *args, **kwargs: {"content": ""})
    monkeypatch.setattr(coordination_docs, "get_operational_runbooks", lambda: {"runbooks": []})

    result = coordination_docs.bootstrap_context()

    assert result["ok"] is True
    assert "Runtime vivo: server" in result["content"]
    assert "2.23.0 / 117 tools" not in result["content"]
    assert "2.23.0 / 117 tools" not in json.dumps(result, ensure_ascii=False)
    assert "Keep useful context." in result["content"]
