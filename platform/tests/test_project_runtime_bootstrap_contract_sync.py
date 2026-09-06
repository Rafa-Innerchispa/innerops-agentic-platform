"""Regression coverage preventing project_runtime_bootstrap contract drift.

The canonical field list lives in project_runtime_registry.BOOTSTRAP_INPUT_SCHEMA.
This suite intentionally fails if runtime, FastMCP wrapper, or the human/tool
catalog expose different parameter sets.
"""
from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import project_runtime_registry  # noqa: E402
from raphiia_openai.mcp_catalog import tool_catalog  # noqa: E402

MCP_SERVER = PLATFORM_ROOT / "inneros_core_runtime" / "mcp_server.py"
LEGACY_CATALOG = PLATFORM_ROOT / "inneros_core_runtime" / "tool_catalog.py"
EXPECTED_FIELDS = set(project_runtime_registry.BOOTSTRAP_INPUT_SCHEMA)


def _mcp_bootstrap_ast() -> ast.FunctionDef:
    tree = ast.parse(MCP_SERVER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "project_runtime_bootstrap":
            return node
    raise AssertionError("project_runtime_bootstrap wrapper not found")


def _resolved() -> dict:
    return {
        "ok": True,
        "capability": "project_runtime_registry",
        "node": "amd",
        "project": {
            "project_id": "sample",
            "repo": "Rafa-Innerchispa/sample",
            "paths": {"amd": "/home/rlopez/projects/sample"},
        },
        "project_path": "/home/rlopez/projects/sample",
    }


def _proc(payload: dict, *, returncode: int = 0):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(payload), stderr="")


def test_runtime_signature_matches_canonical_schema_exactly():
    params = set(inspect.signature(project_runtime_registry.bootstrap_runtime).parameters)
    assert params == EXPECTED_FIELDS


def test_mcp_wrapper_signature_matches_canonical_schema_exactly():
    fn = _mcp_bootstrap_ast()
    params = {arg.arg for arg in fn.args.args}
    assert params == EXPECTED_FIELDS


def test_mcp_wrapper_forwards_every_canonical_field():
    fn = _mcp_bootstrap_ast()
    calls = [node for node in ast.walk(fn) if isinstance(node, ast.Call)]
    bootstrap_calls = [
        node for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "bootstrap_runtime"
    ]
    assert len(bootstrap_calls) == 1
    keywords = {kw.arg for kw in bootstrap_calls[0].keywords}
    assert keywords == EXPECTED_FIELDS


def test_catalog_schema_is_same_canonical_object_contract():
    schema = tool_catalog.describe_tool("project_runtime_bootstrap")["input_schema"]
    assert schema == project_runtime_registry.BOOTSTRAP_INPUT_SCHEMA
    assert schema["base_ref"] == "git ref|null"
    assert schema["expected_sha"] == "git sha|null"


def test_legacy_catalog_uses_the_same_canonical_schema_source():
    text = LEGACY_CATALOG.read_text(encoding="utf-8")
    assert 'project_runtime_registry.BOOTSTRAP_INPUT_SCHEMA if _name == "project_runtime_bootstrap"' in text


@pytest.mark.parametrize("value", ["main", "feature/test", "refs/heads/release-1.2", "v1.0.0", "9aa62d065"])
def test_git_ref_accepts_bounded_safe_values(value):
    assert project_runtime_registry._git_ref(value) == value


@pytest.mark.parametrize("value", ["../main", "main..evil", "refs/heads/x.lock", "x@{1}", r"feature\\evil", "-"])
def test_git_ref_rejects_ambiguous_or_dangerous_values(value):
    with pytest.raises(ValueError, match="invalid_git_ref"):
        project_runtime_registry._git_ref(value)


def test_git_sha_normalizes_hex_and_rejects_non_hex():
    assert project_runtime_registry._git_sha("A1B2C3D") == "a1b2c3d"
    with pytest.raises(ValueError, match="invalid_git_sha"):
        project_runtime_registry._git_sha("not-a-sha")
    with pytest.raises(ValueError, match="invalid_git_sha"):
        project_runtime_registry._git_sha("abc123")


def test_bootstrap_forwards_ref_and_sha_to_node_helper(monkeypatch):
    observed = {}
    monkeypatch.setattr(project_runtime_registry, "resolve_project", lambda **kwargs: _resolved())

    def run_node(node, args, *, input_text="", timeout=120):
        observed.update(json.loads(input_text))
        return _proc({"ok": True, "observed_sha": "9aa62d0654396b3f8246d2b79206e1406459cbc0"})

    monkeypatch.setattr(project_runtime_registry, "_run_node", run_node)
    result = project_runtime_registry.bootstrap_runtime(
        node="amd",
        project_id="sample",
        repo="Rafa-Innerchispa/sample",
        base_ref="chatgpt/test",
        expected_sha="9aa62d065",
        dry_run=True,
    )
    assert result["ok"] is True
    assert result["base_ref"] == "chatgpt/test"
    assert result["expected_sha"] == "9aa62d065"
    assert result["observed_sha"] == "9aa62d0654396b3f8246d2b79206e1406459cbc0"
    assert observed["base_ref"] == "chatgpt/test"
    assert observed["expected_sha"] == "9aa62d065"


def test_bootstrap_fails_closed_on_expected_sha_mismatch(monkeypatch):
    monkeypatch.setattr(project_runtime_registry, "resolve_project", lambda **kwargs: _resolved())
    monkeypatch.setattr(
        project_runtime_registry,
        "_run_node",
        lambda *args, **kwargs: _proc({"ok": True, "observed_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
    )
    result = project_runtime_registry.bootstrap_runtime(
        node="amd",
        project_id="sample",
        repo="Rafa-Innerchispa/sample",
        base_ref="main",
        expected_sha="9aa62d065",
        dry_run=True,
    )
    assert result["ok"] is False
    assert result["result"]["error"] == "expected_sha_mismatch"
    assert result["result"]["expected_sha"] == "9aa62d065"
    assert result["result"]["observed_sha"].startswith("a")


def test_bootstrap_remains_backward_compatible_without_ref_or_sha(monkeypatch):
    observed = {}
    monkeypatch.setattr(project_runtime_registry, "resolve_project", lambda **kwargs: _resolved())

    def run_node(node, args, *, input_text="", timeout=120):
        observed.update(json.loads(input_text))
        return _proc({"ok": True, "observed_sha": ""})

    monkeypatch.setattr(project_runtime_registry, "_run_node", run_node)
    result = project_runtime_registry.bootstrap_runtime(
        node="amd", project_id="sample", repo="Rafa-Innerchispa/sample", dry_run=True
    )
    assert result["ok"] is True
    assert result["base_ref"] == ""
    assert result["expected_sha"] == ""
    assert observed["base_ref"] == ""
    assert observed["expected_sha"] == ""
