from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

PLATFORM = Path(__file__).resolve().parents[1]
PLATFORM_TEXT = str(PLATFORM)
sys.path[:] = [item for item in sys.path if item != PLATFORM_TEXT]
sys.path.insert(0, PLATFORM_TEXT)

for prefix in ("raphiia_openai", "inneros_core_runtime"):
    for module_name in [name for name in sys.modules if name == prefix or name.startswith(prefix + ".")]:
        sys.modules.pop(module_name, None)

from inneros_core_runtime import task_envelope


def _registry_result(project_id: str, repo: str):
    return {
        "ok": True,
        "node": "primary",
        "project_path": f"/home/rlopez/projects/{project_id}",
        "project": {"project_id": project_id, "repo": repo},
    }


def test_task_envelope_import_is_from_current_worktree():
    assert Path(task_envelope.__file__).resolve().is_relative_to(PLATFORM)


def test_verified_local_alpaca_binding_is_exact():
    with mock.patch.object(
        task_envelope.prr,
        "resolve_project",
        return_value=_registry_result("inneros-alpha-alpaca", "Rafa-Innerchispa/inneros-alpha-alpaca"),
    ):
        result = task_envelope.build_task_envelope(
            project_id="inneros-alpha-alpaca",
            repo="Rafa-Innerchispa/inneros-alpha-alpaca",
            base_ref="main",
            task_class="coding",
            execution_lane="local_dev_swarm",
            provider_transport="local_vllm",
            correlation_id="alpaca-runtime-activation-20260901",
        )
    assert result["ok"] is True
    assert result["binding_status"] == "verified"
    assert result["repo"] == "Rafa-Innerchispa/inneros-alpha-alpaca"
    assert result["project_id"] == "inneros-alpha-alpaca"
    assert result["execution_lane"] == "local_dev_swarm"


def test_missing_binding_fails_closed():
    result = task_envelope.build_task_envelope(
        base_ref="main",
        task_class="coding",
        execution_lane="local_dev_swarm",
        provider_transport="local_vllm",
        correlation_id="missing-binding",
    )
    assert result["ok"] is False
    assert result["binding_status"] == "needs_project_binding"
    assert "repo" in result["missing"]


def test_cursor_lane_cannot_be_claimed_by_local_dev_swarm():
    task = {
        "task_id": "ops_36fc23d6155b",
        "execution_lane": "cursor",
        "project_id": "inneros-webmcp",
        "repo": "Rafa-Innerchispa/inneros-webmcp",
        "base_ref": "main",
        "task_class": "coding",
        "provider_transport": "ide_inbox",
        "correlation_id": "cursor-stolen-regression",
    }
    result = task_envelope.validate_local_dev_swarm_task(task)
    assert result["ok"] is False
    assert result["error"] == "execution_lane_not_local_dev_swarm"


def test_codex_lane_cannot_be_claimed_by_local_dev_swarm():
    task = {
        "task_id": "ops_2bb28a5e80bf",
        "execution_lane": "codex",
        "project_id": "inneros-webmcp",
        "repo": "Rafa-Innerchispa/inneros-webmcp",
        "base_ref": "main",
        "task_class": "coding",
        "provider_transport": "external_repair",
        "correlation_id": "codex-stolen-regression",
    }
    result = task_envelope.validate_local_dev_swarm_task(task)
    assert result["ok"] is False
    assert result["error"] == "execution_lane_not_local_dev_swarm"


def test_local_lane_revalidates_registry_before_execution():
    task = {
        "task_id": "ops_alpaca_fixture",
        "execution_lane": "local_dev_swarm",
        "project_id": "inneros-alpha-alpaca",
        "repo": "Rafa-Innerchispa/inneros-alpha-alpaca",
        "base_ref": "main",
        "task_class": "coding",
        "provider_transport": "local_vllm",
        "correlation_id": "alpaca-registry-revalidate",
    }
    with mock.patch.object(
        task_envelope.prr,
        "resolve_project",
        return_value=_registry_result("inneros-alpha-alpaca", "Rafa-Innerchispa/inneros-alpha-alpaca"),
    ):
        result = task_envelope.validate_local_dev_swarm_task(task)
    assert result["ok"] is True
    assert result["repo"] == "Rafa-Innerchispa/inneros-alpha-alpaca"


def test_exact_related_project_migration_requires_registry_proof():
    with mock.patch.object(
        task_envelope.prr,
        "resolve_project",
        return_value=_registry_result("inneros-alpha-alpaca", "Rafa-Innerchispa/inneros-alpha-alpaca"),
    ):
        result = task_envelope.build_task_envelope(
            related_project="Rafa-Innerchispa/inneros-alpha-alpaca",
            base_ref="main",
            task_class="coding",
            execution_lane="local_dev_swarm",
            provider_transport="local_vllm",
            correlation_id="legacy-exact-binding",
        )
    assert result["ok"] is True
    assert result["binding_source"] == "legacy_related_project_exact"
    assert result["repo"] == "Rafa-Innerchispa/inneros-alpha-alpaca"


def test_ambiguous_related_project_is_not_repo_inference():
    result = task_envelope.build_task_envelope(
        related_project="InnerOS Alpaca project",
        base_ref="main",
        task_class="coding",
        execution_lane="local_dev_swarm",
        provider_transport="local_vllm",
        correlation_id="ambiguous-related-project",
    )
    assert result["ok"] is False
    assert result["binding_status"] == "needs_project_binding"


def test_auto_lane_is_not_executable_until_resolved():
    result = task_envelope.build_task_envelope(
        project_id="inneros-alpha-alpaca",
        repo="Rafa-Innerchispa/inneros-alpha-alpaca",
        base_ref="main",
        task_class="coding",
        execution_lane="auto",
        provider_transport="resource_fabric",
        correlation_id="auto-unresolved",
    )
    assert result["ok"] is False
    assert result["binding_status"] == "needs_execution_lane_resolution"
