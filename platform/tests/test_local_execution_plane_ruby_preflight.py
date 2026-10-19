"""Regression coverage for GitLab ContributorOps Ruby toolchain diagnosis."""

from __future__ import annotations

from inneros_core_runtime import local_execution_plane as lep


def _run_with_toolchain(monkeypatch, tmp_path, *, ruby: bool, bundle: bool, command: list[str]):
    records = []
    executions = []
    monkeypatch.setattr(lep, "_repo_config", lambda _repo: {"profile": "ruby-tests-local-only"})
    monkeypatch.setattr(lep, "_worktree_path", lambda _repo, _branch, _conf: tmp_path)
    monkeypatch.setattr(lep, "_record_command_run", lambda key, value: records.append(value))
    monkeypatch.setattr(lep, "_execution_env", lambda: {"PATH": "/isolated/ruby/bin:/usr/bin"})

    def which(binary, *, path):
        assert path == "/isolated/ruby/bin:/usr/bin"
        if binary == "ruby" and ruby:
            return "/isolated/ruby/bin/ruby"
        if binary == "bundle" and bundle:
            return "/isolated/ruby/bin/bundle"
        return None

    monkeypatch.setattr(lep.shutil, "which", which)

    def fake_run(argv, cwd, *, timeout_seconds=120, max_output_bytes=lep.MAX_OUTPUT_BYTES_DEFAULT):
        executions.append(argv)
        return {"ok": True, "returncode": 0, "stdout": "PASS", "stderr": "", "argv": argv}

    monkeypatch.setattr(lep, "_run", fake_run)
    result = lep.run_command_allowlisted(
        "rafagye/gitlab",
        "chatgpt/test-ruby-preflight",
        command,
        "chatgpt",
        "ops_6113b4f0abf7",
        "gitlab-contributorops-ruby-preflight-test",
    )
    return result, records, executions


def test_missing_ruby_and_bundler_fails_before_any_command(monkeypatch, tmp_path):
    result, records, executions = _run_with_toolchain(
        monkeypatch, tmp_path, ruby=False, bundle=False,
        command=["bin/rspec", "spec/services/mcp/tools/search/search_service_spec.rb"],
    )
    assert result["ok"] is False
    assert result["error"] == "ruby_runtime_missing"
    assert result["ruby_available"] is False
    assert result["bundler_available"] is False
    assert records[-1]["status"] == "blocked"
    assert executions == []


def test_ruby_without_bundler_fails_closed(monkeypatch, tmp_path):
    result, _, executions = _run_with_toolchain(
        monkeypatch, tmp_path, ruby=True, bundle=False,
        command=["bundle", "exec", "rspec", "spec/lib/api/helpers/search_helpers_spec.rb"],
    )
    assert result["ok"] is False
    assert result["error"] == "ruby_bundler_missing"
    assert executions == []


def test_existing_local_toolchain_runs_allowlisted_rspec(monkeypatch, tmp_path):
    command = ["bin/rspec", "spec/services/mcp/tools/search/search_service_spec.rb"]
    result, records, executions = _run_with_toolchain(
        monkeypatch, tmp_path, ruby=True, bundle=True, command=command
    )
    assert result["ok"] is True
    assert result["command_result"]["returncode"] == 0
    assert [record["status"] for record in records] == ["running", "completed"]
    assert executions == [command]


def test_git_diagnostics_do_not_require_ruby(monkeypatch, tmp_path):
    command = ["git", "status", "--short", "--branch"]
    result, _, executions = _run_with_toolchain(
        monkeypatch, tmp_path, ruby=False, bundle=False, command=command
    )
    assert result["ok"] is True
    assert executions == [command]


def test_rejects_unallowlisted_command_even_if_ruby_available(monkeypatch, tmp_path):
    result, _, executions = _run_with_toolchain(
        monkeypatch, tmp_path, ruby=True, bundle=True,
        command=["bundle", "exec", "rake", "db:drop"],
    )
    assert result["ok"] is False
    assert result["error"] == "command_not_allowlisted"
    assert executions == []
