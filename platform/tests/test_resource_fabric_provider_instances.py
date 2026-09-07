from __future__ import annotations

import json

from inneros_core_runtime import resource_fabric
from inneros_core_runtime.mcp_catalog import tool_catalog


def test_development_provider_inventory_is_host_specific_and_secret_free() -> None:
    instances = resource_fabric.canonical_development_provider_instances()
    ids = {item["provider_instance_id"] for item in instances}

    assert {
        "codex.amd5",
        "codex.intel4",
        "cursor.amd5",
        "cursor.intel4",
        "antigravity.amd5",
        "antigravity.intel4",
        "qwen.amd5",
        "local.intel4",
    }.issubset(ids)

    serialized = json.dumps(instances, ensure_ascii=False).lower()
    assert "@gmail" not in serialized
    assert "@innerchispa" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized


def test_route_development_provider_prefers_local_qwen_for_coding() -> None:
    result = resource_fabric.route_development_provider(
        project_id="innerops-agentic-platform",
        task_class="coding",
    )

    assert result["ok"] is True
    assert result["selected"]["provider_instance_id"] == "qwen.amd5"
    assert "local_first" in result["reason_codes"]
    assert "capacity_available" in result["reason_codes"]


def test_codex_instance_requires_headless_proof_before_dispatch() -> None:
    result = resource_fabric.route_development_provider(
        project_id="innerops-agentic-platform",
        preferred_instance="codex.intel4",
    )

    assert result["ok"] is False
    assert result["selected"] is None
    assert "manual_session_required" in result["reason_codes"]


def test_resource_fabric_catalog_exposes_development_provider_route() -> None:
    assert "resource_fabric_route_development_provider" in tool_catalog.ALL_MCP_TOOL_NAMES
    described = tool_catalog.describe_tool("resource_fabric_route_development_provider")

    assert described["ok"] is True
    assert described["risk_level"] == "low"

