"""Security checks for the read-only, allowlisted worktree source capability."""

from pathlib import Path

from inneros_core_runtime import local_execution_plane as lep


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        lep,
        "_repo_config",
        lambda _repo: {"allowed_paths": ["ee", "doc"], "worktrees_path": str(tmp_path)},
    )
    monkeypatch.setattr(lep, "_worktree_path", lambda _repo, _branch, _conf: tmp_path)


def test_reads_valid_source_file(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    (tmp_path / "ee").mkdir()
    (tmp_path / "ee" / "search_spec.rb").write_text("expect(true).to eq(true)\n", encoding="utf-8")
    result = lep.read_worktree_file("rafagye/gitlab", "chatgpt/review", "ee/search_spec.rb")
    assert result["ok"] is True
    assert result["content"] == "expect(true).to eq(true)\n"
    assert result["truncated"] is False


def test_limits_content_without_host_file_reads(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "sample.txt").write_text("abcdef", encoding="utf-8")
    result = lep.read_worktree_file("rafagye/gitlab", "chatgpt/review", "doc/sample.txt", max_bytes=3)
    assert result["content"] == "abc"
    assert result["truncated"] is True


def test_denies_secret_and_traversal_paths(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    for path in ("../secrets.txt", "ee/.env", "ee/../.ssh/id_rsa", "/etc/passwd"):
        assert lep.read_worktree_file("rafagye/gitlab", "chatgpt/review", path)["ok"] is False


def test_denies_symlinks_into_denied_repo_paths(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    (tmp_path / "ee").mkdir()
    (tmp_path / ".env").write_text("SECRET_TOKEN=hidden", encoding="utf-8")
    (tmp_path / "ee" / "secret_link").symlink_to(tmp_path / ".env")
    assert lep.read_worktree_file("rafagye/gitlab", "chatgpt/review", "ee/secret_link")["ok"] is False


def test_denies_binary_data_and_redacts_tokens(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    (tmp_path / "ee").mkdir()
    (tmp_path / "ee" / "binary.txt").write_bytes(b"hello\x00world")
    assert lep.read_worktree_file("rafagye/gitlab", "chatgpt/review", "ee/binary.txt")["error"] == "binary_file_denied"
    (tmp_path / "ee" / "source.txt").write_text("api_key=longsecret1234567890", encoding="utf-8")
    result = lep.read_worktree_file("rafagye/gitlab", "chatgpt/review", "ee/source.txt")
    assert result["ok"] is True
    assert result["redacted"] is True
    assert "longsecret" not in result["content"]


def test_requires_governed_worktree_branch(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    assert lep.read_worktree_file("rafagye/gitlab", "main", "ee/spec.rb")["ok"] is False


def test_gitlab_ruby_preflight_fails_closed_before_running(monkeypatch, tmp_path):
    """Existing CI for safe source reads also guards the Ruby runtime contract."""
    monkeypatch.setattr(lep, "_repo_config", lambda _repo: {"profile": "ruby-tests-local-only"})
    monkeypatch.setattr(lep, "_worktree_path", lambda _repo, _branch, _conf: tmp_path)
    monkeypatch.setattr(lep, "_record_command_run", lambda *_args: None)
    monkeypatch.setattr(lep, "_execution_env", lambda: {"PATH": "/usr/bin"})
    monkeypatch.setattr(lep.shutil, "which", lambda binary, *, path: None)

    def deny_spawn(*_args, **_kwargs):
        raise AssertionError("Missing Ruby must not execute RSpec")

    monkeypatch.setattr(lep, "_run", deny_spawn)
    result = lep.run_command_allowlisted(
        "rafagye/gitlab",
        "chatgpt/gitlab-ruby-smoke",
        ["bin/rspec", "spec/lib/api/helpers/search_helpers_spec.rb"],
        "chatgpt",
        "ops_6113b4f0abf7",
        "ruby-preflight-ci-canary",
    )
    assert result["ok"] is False
    assert result["error"] == "ruby_runtime_missing"
    assert result["ruby_available"] is False
    assert result["bundler_available"] is False


def _gitlab_mr_task(repo: str) -> dict:
    return {
        "task_id": "ops_regression_gitlab_mr",
        "status": "proposed",
        "assignee": "dev_swarm",
        "owner": "dev_swarm",
        "execution_lane": "local_dev_swarm",
        "task_class": "coding",
        "project_id": "gitlab",
        "repo": repo,
        "title": "GitLab ContributorOps MR repair",
        "checklist": [
            "Fix actual upstream MR https://gitlab.com/gitlab-org/gitlab/-/merge_requests/257991",
        ],
    }


def test_contributor_mr_never_runs_against_unrelated_inneros_repo():
    from inneros_core_runtime import dev_swarm_scheduler as scheduler

    task = _gitlab_mr_task("Rafa-Innerchispa/innerops-agentic-platform")
    eligible, reason, expected = scheduler._eligible_reason(task)
    assert eligible is False
    assert reason == "external_mr_repo_binding_mismatch"
    assert expected == "rafagye/gitlab"


def test_external_gitlab_repo_binding_keeps_explicit_owner(monkeypatch):
    from inneros_core_runtime import dev_swarm_scheduler as scheduler

    task = _gitlab_mr_task("rafagye/gitlab")
    assert scheduler._structured_repo_binding(task) == "rafagye/gitlab"
    monkeypatch.setattr(
        scheduler.local_execution_plane,
        "repo_policy_status",
        lambda repo: {"ok": repo == "rafagye/gitlab", "write_scope": "worktree"},
    )
    eligible, reason, resolved = scheduler._eligible_reason(task)
    assert (eligible, reason, resolved) == (True, "eligible", "rafagye/gitlab")


def test_explicit_no_auto_dispatch_blocks_even_dev_swarm_retry():
    from inneros_core_runtime import dev_swarm_scheduler as scheduler

    task = _gitlab_mr_task("rafagye/gitlab")
    task.update({"do_not_auto_dispatch": True, "dev_swarm_retry_requested": True})
    eligible, reason, _ = scheduler._eligible_reason(task)
    assert eligible is False
    assert reason == "do_not_auto_dispatch"


def test_gitlab_platform_integration_without_external_mr_is_not_misclassified():
    from inneros_core_runtime import dev_swarm_scheduler as scheduler

    task = {
        "project_id": "gitlab",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "title": "Implement internal GitLab MCP broker handler",
        "checklist": ["Update local broker tests only"],
    }
    allowed, reason, expected = scheduler._contributor_repo_gate(task)
    assert allowed is True
    assert reason is None
    assert expected is None
