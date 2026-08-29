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


def test_python_profile_allows_unittest_discover_without_shell() -> None:
    assert lep._command_allowed(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"], "python-tests") is True
    assert lep._command_allowed(["python", "-m", "unittest", "discover", "-s", "tests", "-v"], "python-tests") is True
    assert lep._command_allowed(["python3", "-m", "unittest;rm", "discover", "-s", "tests"], "python-tests") is False
    assert lep._command_allowed(["bash", "-c", "python3 -m unittest discover -s tests"], "python-tests") is False


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
    assert lep._command_allowed(["go", "test", "-race", "./commands/helpers"], "go_gitlab_runner") is True
    assert lep._command_allowed(["go", "build", "./..."], "go_gitlab_runner") is True
    assert lep._command_allowed(["go", "vet", "./..."], "go_gitlab_runner") is True
    assert lep._command_allowed(["make", "tools"], "go_gitlab_runner") is True
    assert lep._command_allowed(["make", "development_setup"], "go_gitlab_runner") is True
    assert lep._command_allowed(["make", "lint"], "go_gitlab_runner") is True
    assert lep._command_allowed(["gofmt", "-w", "commands/foo.go"], "go_gitlab_runner") is True
    assert lep._command_allowed(["glab", "issue", "view", "39712", "-R", "gitlab-org/gitlab-runner"], "go_gitlab_runner") is True
    assert lep._command_allowed(["glab", "mr", "list", "-R", "gitlab-org/gitlab-runner"], "go_gitlab_runner") is True
    assert lep._command_allowed(["make", "shell"], "go_gitlab_runner") is False
    assert lep._command_allowed(["git", "push", "origin", "main"], "go_gitlab_runner") is False
    assert lep._command_allowed(["glab", "issue", "update", "39712"], "go_gitlab_runner") is False
    assert lep._command_allowed(["glab", "mr", "merge", "1"], "go_gitlab_runner") is False


def test_allowlisted_command_records_durable_status(monkeypatch, tmp_path: Path) -> None:
    records = []

    monkeypatch.setattr(lep, "_repo_config", lambda repo: {"profile": "go_gitlab_runner"})
    monkeypatch.setattr(lep, "_worktree_path", lambda repo, branch, conf: tmp_path)
    monkeypatch.setattr(lep, "_record_command_run", lambda command_run_id, payload: records.append((command_run_id, payload)))
    monkeypatch.setattr(lep, "_run", lambda command, cwd, timeout_seconds=120, max_output_bytes=lep.MAX_OUTPUT_BYTES_DEFAULT: {"ok": True, "returncode": 0, "stdout": "ok", "stderr": "", "argv": command})

    result = lep.run_command_allowlisted(
        "gitlab-community/gitlab-org/gitlab-runner",
        "chatgpt/fix/39708-cache-url-redaction",
        ["go", "build", "./..."],
        "chatgpt_b",
        "ops_fe4f61f14625",
        "gitlab-contrib-runner-39708-local-supervised-20260826",
        timeout_seconds=1200,
    )

    assert result["ok"] is True
    assert result["command_run_id"]
    assert [item[1]["status"] for item in records] == ["running", "completed"]
    assert records[-1][1]["command_result"]["ok"] is True

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
    assert lep._node_package_command_allowed(["npm", "--prefix", "services/femar-mvp-core", "test"], conf) is True
    assert lep._node_package_command_allowed(["npm", "--prefix", "services/femar-mvp-core", "test", "--", "--runInBand"], conf) is True
    assert lep._node_package_command_allowed(["npm", "--prefix", "services/femar-mvp-core", "run", "lint"], conf) is True


def test_local_exec_push_branch_gitlab_auth_is_ephemeral_and_redacted(monkeypatch, tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    calls = []

    monkeypatch.setattr(lep, "_repo_config", lambda repo: {"profile": "go_gitlab_runner"})
    monkeypatch.setattr(lep, "_worktree_path", lambda repo, branch, conf: worktree)
    monkeypatch.setattr(lep, "_validate_remote_for_push", lambda repo, wt, remote: {"ok": True, "remote": "community", "url": "https://gitlab.com/gitlab-community/gitlab-org/gitlab-runner.git"})
    monkeypatch.setattr(lep, "_owner_vault_gitlab_token", lambda: ("glpat-super-secret-token", "owner_vault:gitlab/personal_access_token"))

    def fake_run(command, cwd, timeout_seconds=120, max_output_bytes=lep.MAX_OUTPUT_BYTES_DEFAULT):
        if command == ["git", "branch", "--show-current"]:
            return {"ok": True, "returncode": 0, "stdout": "chatgpt/fix/39708-cache-url-redaction\n", "stderr": "", "argv": command}
        if command == ["git", "status", "--porcelain"]:
            return {"ok": True, "returncode": 0, "stdout": "", "stderr": "", "argv": command}
        if command == ["git", "rev-parse", "--short", "HEAD"]:
            return {"ok": True, "returncode": 0, "stdout": "5ace783e4\n", "stderr": "", "argv": command}
        raise AssertionError(f"unexpected command {command}")

    def fake_run_with_env(command, cwd, env, timeout_seconds=120, max_output_bytes=lep.MAX_OUTPUT_BYTES_DEFAULT):
        calls.append((command, env))
        return {
            "ok": False,
            "returncode": 128,
            "stdout": lep._bounded_output("token glpat-super-secret-token", max_output_bytes),
            "stderr": lep._bounded_output("fatal: could not read Username for https://gitlab.com", max_output_bytes),
            "argv": command,
            "env": {key: lep._redact(value) for key, value in env.items() if key != "GITLAB_TOKEN"},
        }

    monkeypatch.setattr(lep, "_run", fake_run)
    monkeypatch.setattr(lep, "_run_with_env", fake_run_with_env)

    result = lep.push_branch(
        repo="gitlab-community/gitlab-org/gitlab-runner",
        work_branch="chatgpt/fix/39708-cache-url-redaction",
        actor="chatgpt_b",
        task_id="ops_fe4f61f14625",
        correlation_id="gitlab-vault-authenticated-push-mr-20260826",
        idempotency_key="idem-push",
        remote="community",
        dry_run=False,
    )

    assert result["ok"] is False
    assert result["push"]["returncode"] == 128
    assert calls
    assert calls[0][1]["GIT_TERMINAL_PROMPT"] == "0"
    assert "GIT_ASKPASS" in calls[0][1]
    serialized = str(result)
    assert "glpat-super-secret-token" not in serialized
    assert "GITLAB_TOKEN" not in result["push"]["env"]


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


def test_gitlab_push_requires_existing_policy_remote(monkeypatch, tmp_path: Path) -> None:
    repo = "gitlab-community/gitlab-org/gitlab-runner"
    branch = "chatgpt/fix/39708-cache-url-redaction"
    _git(["init", "-b", "main"], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    _git(["config", "user.email", "test@example.invalid"], tmp_path)
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    _git(["add", "README.md"], tmp_path)
    _git(["commit", "-m", "seed"], tmp_path)
    _git(["checkout", "-b", branch], tmp_path)
    _git(["remote", "add", "origin", "https://gitlab.com/rafagye/gitlab-runner.git"], tmp_path)

    monkeypatch.setattr(lep, "_repo_config", lambda repo: {"profile": "go_gitlab_runner"})
    monkeypatch.setattr(lep, "_worktree_path", lambda repo, work_branch, conf: tmp_path)

    missing = lep.push_branch(repo, branch, "codex", "ops_993f4d288688", "gitlab-community-remote-author-20260826", "idem", remote="community", dry_run=True)
    assert missing["ok"] is False
    assert missing["error"] == "remote_missing"

    _git(["remote", "add", "community", "https://gitlab.com/example/wrong.git"], tmp_path)
    mismatch = lep.push_branch(repo, branch, "codex", "ops_993f4d288688", "gitlab-community-remote-author-20260826", "idem2", remote="community", dry_run=True)
    assert mismatch["ok"] is False
    assert mismatch["error"] == "remote_url_mismatch"

    _git(["remote", "set-url", "community", "https://gitlab.com/gitlab-community/gitlab-org/gitlab-runner.git"], tmp_path)
    ok = lep.push_branch(repo, branch, "codex", "ops_993f4d288688", "gitlab-community-remote-author-20260826", "idem3", remote="community", dry_run=True)
    assert ok["ok"] is True
    assert ok["dry_run"] is True
    assert ok["remote_validation"]["url"] == "https://gitlab.com/gitlab-community/gitlab-org/gitlab-runner.git"


def test_configure_remote_uses_exact_policy_url(monkeypatch, tmp_path: Path) -> None:
    repo = "gitlab-community/gitlab-org/gitlab-runner"
    branch = "chatgpt/fix/39708-cache-url-redaction"
    _git(["init", "-b", branch], tmp_path)
    _git(["remote", "add", "origin", "https://gitlab.com/rafagye/gitlab-runner.git"], tmp_path)
    monkeypatch.setattr(lep, "_repo_config", lambda repo: {"profile": "go_gitlab_runner"})
    monkeypatch.setattr(lep, "_worktree_path", lambda repo, work_branch, conf: tmp_path)

    dry = lep.configure_remote(repo, branch, "codex", "ops_993f4d288688", "gitlab-community-remote-author-20260826", "idem", "community", dry_run=True)
    assert dry["ok"] is True
    assert dry["would_execute"] == ["git", "remote", "add", "community", "https://gitlab.com/gitlab-community/gitlab-org/gitlab-runner.git"]

    applied = lep.configure_remote(repo, branch, "codex", "ops_993f4d288688", "gitlab-community-remote-author-20260826", "idem2", "community", dry_run=False)
    assert applied["ok"] is True
    assert applied["after"]["validation"]["community"]["ok"] is True


def test_amend_commit_author_requires_verified_email(monkeypatch, tmp_path: Path) -> None:
    repo = "gitlab-community/gitlab-org/gitlab-runner"
    branch = "chatgpt/fix/39708-cache-url-redaction"
    _git(["init", "-b", branch], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    _git(["config", "user.email", "test@example.invalid"], tmp_path)
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    _git(["add", "README.md"], tmp_path)
    _git(["commit", "-m", "seed"], tmp_path)
    monkeypatch.setattr(lep, "_repo_config", lambda repo: {"profile": "go_gitlab_runner"})
    monkeypatch.setattr(lep, "_worktree_path", lambda repo, work_branch, conf: tmp_path)
    monkeypatch.setenv("RALFIA_VERIFIED_GIT_AUTHORS_JSON", '{"rafagye":{"name":"Rafael Lopez","emails":["rafael@example.invalid"]}}')

    denied = lep.amend_commit_author(repo, branch, "codex", "ops_993f4d288688", "gitlab-community-remote-author-20260826", "idem", username="rafagye", email="other@example.invalid", dry_run=True)
    assert denied["ok"] is False
    assert denied["error"] == "author_email_not_verified"

    ok = lep.amend_commit_author(repo, branch, "codex", "ops_993f4d288688", "gitlab-community-remote-author-20260826", "idem2", username="rafagye", dry_run=True)
    assert ok["ok"] is True
    assert ok["email_verified"] is True
    assert "VERIFIED_EMAIL" in ok["would_execute"][-1]


def test_innerops_platform_prefix_skipped_without_package_json(monkeypatch, tmp_path: Path) -> None:
    from inneros_core_runtime import dev_swarm_scheduler as scheduler

    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "platform").mkdir()
    conf = {
        "profile": "python-tests",
        "package_roots": [".", "platform"],
        "source_path": str(worktree),
    }
    monkeypatch.setattr(lep, "_repo_config", lambda repo: conf)

    roots = scheduler._product_roots_for_repo("Rafa-Innerchispa/innerops-agentic-platform", worktree)
    assert roots == []
    commands = scheduler._test_commands_for_policy(
        "Rafa-Innerchispa/innerops-agentic-platform",
        worktree,
        ["platform/inneros_core_runtime/foo.py"],
    )
    assert not any(cmd[:3] == ["npm", "--prefix", "platform"] for cmd in commands)
    assert lep._node_package_command_allowed(
        ["npm", "--prefix", "platform", "test", "--", "--runInBand"],
        conf,
        base=worktree,
    ) is False


def test_innerops_platform_prefix_allowed_when_package_json_exists(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    platform = worktree / "platform"
    platform.mkdir(parents=True)
    (platform / "package.json").write_text('{"scripts":{"test":"node test.js"}}', encoding="utf-8")
    conf = {
        "profile": "python-tests",
        "package_roots": ["platform"],
        "source_path": str(worktree),
    }

    assert lep._node_package_command_allowed(
        ["npm", "--prefix", "platform", "test", "--", "--runInBand"],
        conf,
        base=worktree,
    ) is True
    assert lep._node_package_command_allowed(["npm", "--prefix", "platform", "ci"], conf, base=worktree) is True
