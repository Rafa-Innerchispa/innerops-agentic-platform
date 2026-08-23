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
