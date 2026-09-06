from __future__ import annotations

from pathlib import Path

from inneros_core_runtime import local_execution_plane, mcp_profiles, tool_catalog


def test_host_approval_dry_run_is_scoped_and_bounded() -> None:
    result = local_execution_plane.issue_host_approval(
        action="peer_python_runtime:venv",
        repo="Rafa-Innerchispa/hyperloom-r9700-anthropic-bridge",
        project_id="hyperloom-r9700-anthropic-bridge",
        node="amd",
        actor="chatgpt",
        task_id="ops_73193db2e5a2",
        correlation_id="hyperloom-r9700-peerfs-remote-fix-20260904",
        ttl_minutes=120,
        reason="bounded venv bootstrap",
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    scope = result["would_issue"]
    assert scope["action"] == "peer_python_runtime:venv"
    assert scope["repo"] == "Rafa-Innerchispa/hyperloom-r9700-anthropic-bridge"
    assert scope["project_id"] == "hyperloom-r9700-anthropic-bridge"
    assert scope["node"] == "amd"
    assert scope["ttl_minutes"] == 60


def test_host_approval_tools_are_catalogued() -> None:
    wanted = {"local_exec_host_approval_issue", "local_exec_host_approval_validate"}

    assert wanted.issubset(set(tool_catalog.ALL_MCP_TOOL_NAMES))
    for name in wanted:
        assert name in tool_catalog.TOOL_DEFINITIONS


def test_mcp_host_approval_endpoint_uses_local_execution_plane() -> None:
    source = (Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")

    assert "from raphiia_openai import local_execution_plane" in source
    assert 'scoped_action = f"{tool}:{action}" if tool else action' in source
    assert "local_execution_plane.issue_host_approval" in source
    assert "local_execution_plane.validate_host_approval" in source


def test_peer_python_profiles_can_issue_host_approval() -> None:
    for profile_name in ("owner_dev", "peer_ops", "local_fleet_full"):
        profile = mcp_profiles.PROFILES[profile_name]
        tools = set(profile["tools"])
        assert "peer_python_runtime" in tools
        assert "local_exec_host_approval_issue" in tools
        assert "local_exec_host_approval_validate" in tools

    validation = mcp_profiles.validate_profiles()
    approval_unknown = [
        err
        for err in validation.get("errors", [])
        if err.get("code") == "unknown_tools"
        and any(name in set(err.get("tools") or []) for name in ("local_exec_host_approval_issue", "local_exec_host_approval_validate"))
    ]
    approval_limit = [
        err
        for err in validation.get("errors", [])
        if err.get("code") == "tool_limit_exceeded" and err.get("profile") in {"owner_dev", "peer_ops", "local_fleet_full"}
    ]
    assert approval_unknown == []
    assert approval_limit == []
