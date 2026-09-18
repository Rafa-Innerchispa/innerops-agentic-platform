from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


def _load_runtime_module(relative_path: str, module_name: str):
    module_path = PLATFORM_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("relative_path", "module_name"),
    [
        ("raphiia_openai/local_execution_plane.py", "test_raphiia_local_execution_plane"),
        ("inneros_core_runtime/local_execution_plane.py", "test_inneros_local_execution_plane"),
    ],
)
def test_prepare_repo_narrow_fetches_requested_branch_for_empty_source(
    tmp_path: Path,
    monkeypatch,
    relative_path: str,
    module_name: str,
) -> None:
    lep = _load_runtime_module(relative_path, module_name)
    branch = "chatgpt/607885-versioned-method-naming"

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(["init", "-b", "main"], seed)
    _git(["config", "user.name", "Test"], seed)
    _git(["config", "user.email", "test@example.invalid"], seed)
    (seed / "README.md").write_text("main\n", encoding="utf-8")
    _git(["add", "README.md"], seed)
    _git(["commit", "-m", "seed main"], seed)
    _git(["checkout", "-b", branch], seed)
    (seed / "branch.txt").write_text("requested branch\n", encoding="utf-8")
    _git(["add", "branch.txt"], seed)
    _git(["commit", "-m", "seed requested branch"], seed)
    expected_head = _git(["rev-parse", "HEAD"], seed).stdout.strip()

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(seed), str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )

    source = tmp_path / "source"
    source.mkdir()
    _git(["init"], source)
    _git(["remote", "add", "origin", str(remote)], source)

    conf = {
        "profile": "python-tests",
        "source_path": str(source),
        "allowed_paths": ["."],
        "package_roots": ["."],
        "worktrees_path": str(tmp_path / "worktrees"),
    }
    monkeypatch.setattr(lep, "_repo_config", lambda repo: conf)

    result = lep.prepare_repo(
        repo="Rafa-Innerchispa/gitlab-community-contrib",
        base_ref=branch,
        actor="chatgpt",
        task_id="ops_test",
        correlation_id="corr-test",
        idempotency_key="idem-test",
    )

    assert result["ok"] is True
    assert result["narrow_fetch"] is True
    assert result["hydrated_ref"] == f"refs/remotes/origin/{branch}"
    assert "--all" not in result["fetch"]["argv"]
    assert "--depth" in result["fetch"]["argv"]
    assert "--filter=blob:none" in result["fetch"]["argv"]
    assert result["fetch"]["argv"][-2] == "origin"
    assert result["fetch"]["argv"][-1] == (
        f"+refs/heads/{branch}:refs/remotes/origin/{branch}"
    )
    assert _git(["rev-parse", "HEAD"], source).stdout.strip() == expected_head
    assert _git(["branch", "--show-current"], source).stdout.strip() == ""
    assert (source / "branch.txt").read_text(encoding="utf-8") == "requested branch\n"


def test_gitlab_community_contrib_remote_policy_is_exact() -> None:
    lep = _load_runtime_module(
        "inneros_core_runtime/local_execution_plane.py",
        "test_inneros_remote_policy",
    )
    assert lep._remote_policy("Rafa-Innerchispa/gitlab-community-contrib") == {
        "origin": "https://gitlab.com/gitlab-community/gitlab-org/gitlab.git"
    }
