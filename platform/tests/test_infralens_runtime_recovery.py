from __future__ import annotations

import asyncio
import json
from pathlib import Path

from inneros_core_runtime import temporal_activities as ta
from inneros_core_runtime import local_execution_plane as lep


def test_completion_gate_rejects_repo_not_allowlisted_executor_failure() -> None:
    envelope = {
        "task_id": "ops_infralens_gate",
        "task_class": "platform",
        "execution_lane": "local_dev_swarm",
    }
    agent_result = {
        "ok": False,
        "files_count": 0,
        "objective_files_count": 0,
        "objective_paths": [],
        "test_results": {
            "exit_code": None,
            "ok": False,
            "reason": "repo_not_allowlisted",
        },
        "bounded_executor": {
            "command_audit": {
                "ok": False,
                "error": "repo_not_allowlisted",
            }
        },
    }

    gate = asyncio.run(ta.activity_validate_completion_gate(envelope, agent_result))

    assert gate["passed"] is False
    assert "repo_not_allowlisted" in gate["error"]


def test_platform_mutation_cannot_pass_with_zero_objective_files() -> None:
    envelope = {
        "task_id": "ops_platform_zero",
        "task_class": "platform",
        "execution_lane": "local_dev_swarm",
    }
    agent_result = {
        "ok": True,
        "files_count": 0,
        "objective_files_count": 0,
        "objective_paths": [],
        "test_results": {
            "exit_code": 0,
            "ok": True,
        },
    }

    gate = asyncio.run(ta.activity_validate_completion_gate(envelope, agent_result))

    assert gate["passed"] is False
    assert "platform mutation requires objective file evidence" in gate["error"]


def test_infralens_is_allowlisted_in_local_execution_policy() -> None:
    profile = lep.DEFAULT_REPO_PROFILES["Rafa-Innerchispa/infralens-ocr-amd"]
    assert profile["profile"] == "python-tests"
    assert "app" in profile["allowed_paths"]
    assert "demo" in profile["allowed_paths"]
    assert "Dockerfile.presentation" in profile["allowed_paths"]
    assert "docker-compose.presentation.yml" in profile["allowed_paths"]


def test_infralens_is_registered_in_canonical_runtime_registry() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = json.loads((root / "var" / "project_runtime_registry" / "registry.json").read_text(encoding="utf-8"))
    project = registry["projects"]["infralens-ocr-amd"]
    assert project["repo"] == "Rafa-Innerchispa/infralens-ocr-amd"
    assert project["write_scope"] == "worktree_branch_only"
    assert project["paths"]["amd"].endswith("/workspaces/infralens-ocr-amd")
