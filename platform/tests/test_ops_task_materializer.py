from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from inneros_core_runtime import ops_task_materializer as otm


def test_meta_repair_task_uses_platform_repo_not_gitlab() -> None:
    task = {
        "task_id": "ops_8691cdde5c05",
        "correlation_id": "cursor-worktree-claim-repair-20261017",
        "repo": None,
        "objective": "Reparar claim/worktree en innerops-agentic-platform; caso GitLab ContributorOps ops_6113",
        "title": "P0 reparar claim/worktree Cursor",
    }
    out = otm.resolve_executable_repo(task)
    assert out["ok"] is True
    assert out["repo"] == "Rafa-Innerchispa/innerops-agentic-platform"
    assert out["source"] == "objective_platform_repo"


def test_resolve_github_repo_from_structured_task() -> None:
    task = {
        "task_id": "ops_abc123",
        "repo": "Rafa-Innerchispa/inneros-alexa-amd-draft033",
        "base_ref": "main",
        "correlation_id": "draft-test",
    }
    out = otm.resolve_executable_repo(task)
    assert out["ok"] is True
    assert out["repo"] == "Rafa-Innerchispa/inneros-alexa-amd-draft033"
    assert out["materializer_lane"] == "github"


def test_gitlab_fork_from_related_ops_payload_reference() -> None:
    task = {
        "task_id": "ops_child",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "correlation_id": "gitlab-contributorops-repair-20261017",
        "title": "GitLab ContributorOps repair",
        "payload": {"related_ops": ["ops_parent"]},
    }
    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.return_value = {"payload": {"repo": "rafagye/gitlab"}}
    with patch("raphiia_openai.mongo_store.get_db", return_value=db), patch.object(
        otm, "_local_gitlab_source_ready", return_value=True
    ):
        out = otm.resolve_executable_repo(task)
    assert out["ok"] is True
    assert out["repo"] == "rafagye/gitlab"
    assert out["source"] == "payload_or_related_gitlab_fork_reference"


def test_gitlab_contributor_ops_ignores_contaminated_github_repo() -> None:
    task = {
        "task_id": "ops_01d9c75d71b0",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "correlation_id": "gitlab-contributorops-repair-20261017",
        "title": "P0 reparar GitLab ContributorOps ops_6113b4f0abf7",
        "payload": {
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "related_ops": ["ops_6113b4f0abf7"],
        },
    }
    fork = {
        "ok": True,
        "write_fork_project": "rafagye/gitlab",
        "write_fork_default_branch": "master",
    }
    with patch.object(otm, "_gitlab_fork_hint_from_related_ops", return_value=None), patch(
        "inneros_core_runtime.gitlab_contributor_policy.resolve_authenticated_write_fork",
        return_value=fork,
    ):
        out = otm.resolve_executable_repo(task)
    assert out["ok"] is True
    assert out["repo"] == "rafagye/gitlab"
    assert out["base_ref"] == "master"
    assert any("contaminated" in w for w in (out.get("warnings") or []))


def test_gitlab_fork_from_payload_repo() -> None:
    task = {
        "task_id": "ops_gitlab1",
        "correlation_id": "gitlab-contributorops-20261001",
        "payload": {"repo": "rafagye/gitlab"},
    }
    out = otm.resolve_executable_repo(task)
    assert out["ok"] is True
    assert out["repo"] == "rafagye/gitlab"


def test_related_ops_branch_reference_only_for_gitlab_contributor() -> None:
    task = {
        "task_id": "ops_child",
        "repo": "Rafa-Innerchispa/demo",
        "correlation_id": "gitlab-contributorops-repair-20261017",
        "title": "GitLab ContributorOps follow-up",
        "payload": {"related_ops": ["ops_parent"]},
    }
    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.return_value = {
        "work_branch": "chatgpt/feature-from-parent",
        "repo": "rafagye/gitlab",
    }
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        branch = otm.resolve_work_branch(task, repo="Rafa-Innerchispa/demo", provider="cursor")
    assert branch == "chatgpt/feature-from-parent"


def test_stale_worktree_cleanup_in_preflight(tmp_path: Path) -> None:
    stale = tmp_path / "wt"
    stale.mkdir()
    (stale / "orphan.txt").write_text("x", encoding="utf-8")
    task = {
        "task_id": "ops_stale1",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "work_branch": "cursor/ops-stale1",
        "base_ref": "main",
    }
    conf = {
        "source_path": str(tmp_path / "src"),
        "worktrees_path": str(tmp_path / "worktrees"),
        "profile": "python-tests",
    }
    src = tmp_path / "src"
    src.mkdir()
    (src / ".git").mkdir()
    mat = {
        "ok": True,
        "repo": task["repo"],
        "base_ref": "main",
        "work_branch": task["work_branch"],
        "materializer_lane": "github",
        "source": "structured_repo",
    }
    with patch.object(otm, "materialize_ops_task_execution", return_value=mat), patch(
        "inneros_core_runtime.local_execution_plane._repo_config",
        return_value=conf,
    ), patch(
        "inneros_core_runtime.local_execution_plane._worktree_path",
        return_value=stale,
    ), patch(
        "inneros_core_runtime.local_execution_plane.create_worktree",
        return_value={"ok": True, "worktree": str(stale), "verified_exists": True},
    ):
        pf = otm.preflight_claim_worktree(task, provider="cursor", repair_stale=True)
    assert pf["ok"] is True
    assert pf["materialization"].get("stale_worktree_cleaned") is True
    assert not stale.exists() or (stale / ".git").exists()


def test_authorization_blockers_fail_fast_when_source_missing(tmp_path: Path) -> None:
    task = {
        "task_id": "ops_block",
        "repo": "Rafa-Innerchispa/missing-repo",
        "work_branch": "cursor/ops-block",
    }
    conf = {"source_path": str(tmp_path / "nope"), "worktrees_path": str(tmp_path / "wt")}
    mat = {
        "ok": True,
        "repo": task["repo"],
        "base_ref": "main",
        "work_branch": task["work_branch"],
    }
    with patch.object(otm, "materialize_ops_task_execution", return_value=mat), patch(
        "inneros_core_runtime.local_execution_plane._repo_config",
        return_value=conf,
    ):
        gate = otm.authorization_blockers(task, provider="cursor")
    assert gate["ok"] is False
    assert gate["error"] == "worktree_preflight_source_repo_missing"


def test_authorize_reuses_existing_owner_grant() -> None:
    from inneros_core_runtime import interactive_ops_runner as ior

    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.return_value = {"task_id": "ops_x", "owner_authorized_at": "2026-01-01T00:00:00+00:00"}
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = ior.authorize_ops_task("cursor", "ops_x")
    assert out["ok"] is True
    assert out.get("authorization_reused") is True
    col.find_one_and_update.assert_not_called()
