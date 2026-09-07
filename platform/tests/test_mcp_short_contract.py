from __future__ import annotations

import json
from types import SimpleNamespace

from inneros_core_runtime import mcp_diagnostics, project_runtime_registry
from inneros_core_runtime.mcp_catalog import tool_catalog


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


def test_project_runtime_bootstrap_passes_ref_and_sha_to_node_helper(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(project_runtime_registry, "_core_root", lambda: tmp_path)
    project_runtime_registry.register_project(
        "innerops-agentic-platform",
        "Rafa-Innerchispa/innerops-agentic-platform",
        str(tmp_path / "workspaces" / "innerops-agentic-platform"),
        actor="test",
    )

    def fake_run_node(node, args, *, input_text="", timeout=120):
        captured["payload"] = json.loads(input_text)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "observed_sha": "abc123"}), stderr="")

    monkeypatch.setattr(project_runtime_registry, "_run_node", fake_run_node)

    result = project_runtime_registry.bootstrap_runtime(
        node="primary",
        project_id="innerops-agentic-platform",
        repo="Rafa-Innerchispa/innerops-agentic-platform",
        base_ref="main",
        expected_sha="abc123",
        dry_run=False,
    )

    assert result["ok"] is True
    assert captured["payload"]["base_ref"] == "main"
    assert captured["payload"]["expected_sha"] == "abc123"


def test_project_runtime_bootstrap_helper_mismatch_fails_closed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(project_runtime_registry, "_core_root", lambda: tmp_path)
    project_runtime_registry.register_project(
        "innerops-agentic-platform",
        "Rafa-Innerchispa/innerops-agentic-platform",
        str(tmp_path / "workspaces" / "innerops-agentic-platform"),
        actor="test",
    )

    def fake_run_node(node, args, *, input_text="", timeout=120):
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({"ok": False, "error": "expected_sha_mismatch", "observed_sha": "def456"}),
            stderr="",
        )

    monkeypatch.setattr(project_runtime_registry, "_run_node", fake_run_node)

    result = project_runtime_registry.bootstrap_runtime(
        node="primary",
        project_id="innerops-agentic-platform",
        repo="Rafa-Innerchispa/innerops-agentic-platform",
        base_ref="main",
        expected_sha="abc123",
        dry_run=False,
    )

    assert result["ok"] is False
    assert result["result"]["error"] == "expected_sha_mismatch"
