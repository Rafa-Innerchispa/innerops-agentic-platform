from __future__ import annotations

import os
import subprocess
from pathlib import Path

from raphiia_openai import local_execution_plane as lep


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _seed_repo(tmp_path: Path, monkeypatch) -> tuple[str, str]:
    root = tmp_path / "local_exec"
    source = root / "repos" / "Rafa-Innerchispa__ralphiia-ecosystem-core"
    source.mkdir(parents=True)
    _git(["init", "-b", "main"], source)
    _git(["config", "user.name", "Test"], source)
    _git(["config", "user.email", "test@example.invalid"], source)
    (source / "docs").mkdir()
    (source / "docs" / "README.md").write_text("before\n", encoding="utf-8")
    _git(["add", "-A"], source)
    _git(["commit", "-m", "seed"], source)
    monkeypatch.setenv("RALFIA_LOCAL_EXEC_ROOT", str(root))
    return "Rafa-Innerchispa/ralphiia-ecosystem-core", "codex/test-local-exec"


def test_denies_unallowlisted_repo() -> None:
    result = lep.inspect_repo("Other/repo")
    assert result["ok"] is False
    assert "repo_not_allowlisted" in result["error"]


def test_default_root_lives_under_inneros_core(monkeypatch) -> None:
    monkeypatch.delenv("RALFIA_LOCAL_EXEC_ROOT", raising=False)
    monkeypatch.delenv("INNEROS_CORE_ROOT", raising=False)
    normalized = str(lep._root()).replace("\\", "/")
    assert normalized.endswith("/home/rlopez/inneros/inneros_core/var/local_execution")
    assert "/projects/" not in normalized


def test_denies_secret_path(tmp_path: Path, monkeypatch) -> None:
    repo, branch = _seed_repo(tmp_path, monkeypatch)
    created = lep.create_worktree(repo, "main", branch, "codex", "task1", "corr-1234", "idem-123456")
    assert created["ok"] is True
    result = lep.write_file(repo, branch, ".env", "TOKEN=x", "codex", "task1", "corr-1234", "idem-abcdef")
    assert result["ok"] is False
    assert "secret_or_generated_path_denied" in result["error"]


def test_denies_shell_metachar_command(tmp_path: Path, monkeypatch) -> None:
    repo, branch = _seed_repo(tmp_path, monkeypatch)
    created = lep.create_worktree(repo, "main", branch, "codex", "task1", "corr-1234", "idem-123456")
    assert created["ok"] is True
    result = lep.run_command_allowlisted(repo, branch, ["git", "status", "--short", "--branch;rm"], "codex", "task1", "corr-1234")
    assert result["ok"] is False
    assert result["error"] == "command_not_allowlisted"


def test_worktree_write_check_and_commit(tmp_path: Path, monkeypatch) -> None:
    repo, branch = _seed_repo(tmp_path, monkeypatch)
    created = lep.create_worktree(repo, "main", branch, "codex", "task1", "corr-1234", "idem-123456")
    assert created["ok"] is True
    written = lep.write_file(repo, branch, "docs/LOCAL.md", "ok\n", "codex", "task1", "corr-1234", "idem-write")
    assert written["ok"] is True
    checked = lep.run_command_allowlisted(repo, branch, ["git", "diff", "--check"], "codex", "task1", "corr-1234")
    assert checked["ok"] is True
    _git(["config", "user.name", "Test"], Path(created["worktree"]))
    _git(["config", "user.email", "test@example.invalid"], Path(created["worktree"]))
    committed = lep.commit_branch(repo, branch, "docs: local execution test", "codex", "task1", "corr-1234", "idem-commit")
    assert committed["ok"] is True
    assert committed["head"]


def test_rafagye_gitlab_runner_can_be_authorized_narrowly(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "local_exec"
    core = tmp_path / "inneros_core"
    (core / "workspaces" / "gitlab-runner").mkdir(parents=True)
    monkeypatch.setenv("RALFIA_LOCAL_EXEC_ROOT", str(root))
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(core))
    result = lep.repo_authorize(
        repo="rafagye/gitlab-runner",
        actor="codex",
        task_id="ops_00297f4cb505",
        correlation_id="gitlab-contrib-runner-39563-20260826-home-a",
        approval_id="owner-approved-fixture",
        repo_class="external_fork_docs_only",
        write_scope="worktree_branch_only",
        allowed_paths=["docs/configuration/init.md", "README.md", "CONTRIBUTING.md", "AGENTS.md"],
        allowed_commands_profile="docs_git_markdown",
        package_roots=["."],
        dry_run=False,
    )
    assert result["ok"] is True
    conf = lep._repo_config("rafagye/gitlab-runner")
    assert conf["profile"] == "docs_git_markdown"
    assert lep._validate_relative_path("docs/configuration/init.md", conf["allowed_paths"])
    try:
        lep._validate_relative_path("scripts/runner-helper.sh", conf["allowed_paths"])
    except PermissionError as exc:
        assert str(exc) == "path_not_allowed_for_repo_profile"
    else:
        raise AssertionError("GitLab runner policy must stay docs-only")


def test_unapproved_external_owner_still_denied(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALFIA_LOCAL_EXEC_ROOT", str(tmp_path / "local_exec"))
    result = lep.repo_authorize(
        repo="gitlab-org/gitlab-runner",
        actor="codex",
        task_id="ops_00297f4cb505",
        correlation_id="gitlab-contrib-runner-39563-20260826-home-a",
        approval_id="owner-approved-fixture",
        dry_run=False,
    )
    assert result["ok"] is False
    assert result["error"] == "repo_owner_not_allowlisted"




def test_gitlab_community_nested_runner_can_be_authorized_narrowly(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "local_exec"
    core = tmp_path / "inneros_core"
    repo_path = core / "workspaces" / "gitlab-runner"
    repo_path.mkdir(parents=True)
    (repo_path / ".git").mkdir()
    monkeypatch.setenv("RALFIA_LOCAL_EXEC_ROOT", str(root))
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(core))

    result = lep.repo_authorize(
        repo="gitlab-community/gitlab-org/gitlab-runner",
        actor="codex",
        task_id="ops_e47da3075512",
        correlation_id="gitlab-contrib-runner-39712-20260826-codex",
        approval_id="owner-approved-fixture",
        repo_class="external_fork_docs_only",
        write_scope="worktree",
        allowed_paths=[
            "AGENTS.md",
            "CONTRIBUTING.md",
            "docs/AGENTS.md",
            ".gitlab/merge_request_templates/Documentation.md",
            "docs/executors/docker.md",
        ],
        allowed_commands_profile="go_gitlab_runner",
        package_roots=["."],
        dry_run=False,
    )

    assert result["ok"] is True
    assert result["registered"]["project"]["project_id"] == "gitlab-runner"
    assert result["registered"]["project"]["repo"] == "gitlab-community/gitlab-org/gitlab-runner"
    assert result["registered"]["project"]["paths"]["primary"] == str(repo_path)
    conf = lep._repo_config("gitlab-community/gitlab-org/gitlab-runner")
    assert conf["profile"] == "go_gitlab_runner"
    assert conf["package_roots"] == ["."]
    assert lep._validate_relative_path("docs/executors/docker.md", conf["allowed_paths"])
    try:
        lep._validate_relative_path("commands/helpers.go", conf["allowed_paths"])
    except PermissionError as exc:
        assert str(exc) == "path_not_allowed_for_repo_profile"
    else:
        raise AssertionError("Nested GitLab community fork must stay docs-only")

def test_gitlab_runner_go_profile_allows_only_safe_go_and_gitlab_reads() -> None:
    assert lep._command_allowed(["go", "version"], "go_gitlab_runner") is True
    assert lep._command_allowed(["go", "test", "./commands", "-run", "NoSuchTest", "-count=0"], "go_gitlab_runner") is True
    assert lep._command_allowed(["gofmt", "-w", "commands/foo.go"], "go_gitlab_runner") is True
    assert lep._command_allowed(["glab", "issue", "view", "39712", "-R", "gitlab-org/gitlab-runner"], "go_gitlab_runner") is True
    assert lep._command_allowed(["glab", "mr", "list", "-R", "gitlab-org/gitlab-runner"], "go_gitlab_runner") is True
    assert lep._command_allowed(["git", "push", "origin", "main"], "go_gitlab_runner") is False
    assert lep._command_allowed(["glab", "issue", "update", "39712"], "go_gitlab_runner") is False
    assert lep._command_allowed(["glab", "mr", "merge", "1"], "go_gitlab_runner") is False

def test_workforce_nested_package_root_allows_npm_ci(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "local_exec"
    core = tmp_path / "inneros_core"
    source = core / "workspaces" / "innerspark-workforce-ai"
    source.mkdir(parents=True)
    (source / ".git").mkdir()
    monkeypatch.setenv("RALFIA_LOCAL_EXEC_ROOT", str(root))
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(core))
    conf = lep._repo_config("Rafa-Innerchispa/innerspark-workforce-ai")
    assert "services/femar-mvp-core" in conf["package_roots"]
    assert lep._node_package_command_allowed(["npm", "--prefix", "services/femar-mvp-core", "ci"], conf) is True
    assert lep._node_package_command_allowed(["npm", "ci", "--prefix", "services/femar-mvp-core"], conf) is True


def test_node_install_outside_package_roots_still_blocked(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "local_exec"
    core = tmp_path / "inneros_core"
    source = core / "workspaces" / "innerspark-workforce-ai"
    source.mkdir(parents=True)
    (source / ".git").mkdir()
    monkeypatch.setenv("RALFIA_LOCAL_EXEC_ROOT", str(root))
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(core))
    conf = lep._repo_config("Rafa-Innerchispa/innerspark-workforce-ai")
    assert lep._node_package_command_allowed(["npm", "--prefix", "other-service", "ci"], conf) is False
    assert lep._node_package_command_allowed(["npm", "--prefix", "../outside", "ci"], conf) is False
    assert lep._node_package_command_allowed(["npm", "--prefix", "services/femar-mvp-core", "run", "evil"], conf) is False
