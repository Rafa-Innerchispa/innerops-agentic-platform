from pathlib import Path

from inneros_core_runtime import local_execution_plane as lep


def test_nested_gitlab_runner_uses_go_policy_before_generic_gitlab_policy(tmp_path: Path, monkeypatch) -> None:
    core = tmp_path / "inneros_core"
    repo = core / "workspaces" / "gitlab-runner"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(core))
    monkeypatch.setenv("RALFIA_LOCAL_EXEC_ROOT", str(core / "var" / "local_execution"))

    conf = lep._owner_approved_repo_config("gitlab-community/gitlab-org/gitlab-runner")

    assert conf is not None
    assert conf["profile"] == "go_gitlab_runner"
    assert conf["contributor_upstream"] == "gitlab-org/gitlab-runner"
    assert conf["contributor_write_repo"] == "gitlab-community/gitlab-org/gitlab-runner"
    assert lep._validate_relative_path("shells/bash.go", conf["allowed_paths"]) == "shells/bash.go"
    assert lep._validate_relative_path("commands/helpers.go", conf["allowed_paths"]) == "commands/helpers.go"


def test_runner_policy_does_not_fall_back_to_ruby_paths(tmp_path: Path, monkeypatch) -> None:
    core = tmp_path / "inneros_core"
    repo = core / "workspaces" / "gitlab-runner"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(core))
    monkeypatch.setenv("RALFIA_LOCAL_EXEC_ROOT", str(core / "var" / "local_execution"))

    conf = lep._owner_approved_repo_config("gitlab-community/gitlab-org/gitlab-runner")

    assert conf is not None
    assert conf["profile"] != "ruby-tests-local-only"
    assert "shells" in conf["allowed_paths"]
    assert "commands" in conf["allowed_paths"]
