from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inneros_core_runtime import capability_router, project_runtime_registry


def test_route_tools_accepts_published_optional_bounds():
    result = capability_router.route_tools(
        title="contract test",
        requested_profile="chatgpt_compact",
        granted_scopes=["ralfia:read"],
        max_risk="low",
        for_model="small",
        max_tools=3,
    )
    assert result["ok"] is True
    assert result["for_model"] == "small"
    assert result["max_tools"] == 3
    assert result["tool_count"] <= 3


def test_project_runtime_bootstrap_forwards_git_contract(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        project_runtime_registry,
        "resolve_project",
        lambda **kwargs: {
            "node": "primary",
            "project_path": "/home/rlopez/projects/example",
            "project": {"repo": "Rafa-Innerchispa/example"},
        },
    )

    def fake_run(node, args, *, input_text="", timeout=120):
        captured["node"] = node
        captured["payload"] = json.loads(input_text)
        return subprocess.CompletedProcess(args, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(project_runtime_registry, "_run_node", fake_run)
    result = project_runtime_registry.bootstrap_runtime(
        project_id="example",
        repo="Rafa-Innerchispa/example",
        base_ref="main",
        expected_sha="a" * 40,
        dry_run=True,
    )
    assert result["ok"] is True
    assert captured["payload"]["base_ref"] == "main"
    assert captured["payload"]["expected_sha"] == "a" * 40


def test_browser_wrapper_does_not_forward_unsupported_legacy_options():
    source = (ROOT / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "agent_browser_run_task"
    )
    calls = [
        node for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "agent_browser_run_task"
    ]
    assert len(calls) == 1
    forwarded = {kw.arg for kw in calls[0].keywords}
    assert "local_preview" not in forwarded
    assert "loopback_ports" not in forwarded
    assert any(
        isinstance(node, ast.Constant)
        and node.value == "unsupported_browser_run_task_options"
        for node in ast.walk(fn)
    )
