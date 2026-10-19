"""Offline regression for SHA-pinned, non-mutating-by-default runtime synchronization."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_platform_runtime_from_git.sh"


def _cmd(args: list[str], *, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        args, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=30
    )


@pytest.fixture
def staging(tmp_path: Path):
    assert shutil.which("rsync"), "CI requires rsync to exercise real dry-run/apply behavior"
    repo = tmp_path / "repo"
    ws = repo / "platform"
    runtime = tmp_path / "runtime"
    backup = tmp_path / "backups"
    for sub in ("inneros_core_runtime", "scripts", "systemd"):
        (ws / sub).mkdir(parents=True)
        (runtime / sub).mkdir(parents=True)
    for name in ("dev_swarm_scheduler.py", "local_execution_plane.py"):
        (ws / "inneros_core_runtime" / name).write_text("SOURCE = 'approved'\n")
        (runtime / "inneros_core_runtime" / name).write_text("SOURCE = 'old'\n")
    (ws / "scripts" / "inneros_coordination_cycle.py").write_text("VERSION = 2\n")
    (runtime / "scripts" / "inneros_coordination_cycle.py").write_text("VERSION = 1\n")
    (ws / "systemd" / "test.timer").write_text("Description=test\n")
    _cmd(["git", "init", "-q", "-b", "main"], cwd=repo)
    _cmd(["git", "config", "user.email", "test@example.invalid"], cwd=repo)
    _cmd(["git", "config", "user.name", "InnerOS Test"], cwd=repo)
    _cmd(
        ["git", "remote", "add", "origin", "https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git"],
        cwd=repo,
    )
    assert _cmd(["git", "add", "platform"], cwd=repo).returncode == 0
    assert _cmd(["git", "commit", "-qm", "fixture"], cwd=repo).returncode == 0
    sha = _cmd(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    env = {
        **os.environ,
        "INNEROS_PLATFORM_GIT": str(ws),
        "INNEROS_PLATFORM_RUNTIME": str(runtime),
        "INNEROS_PLATFORM_BACKUP_DIR": str(backup),
    }
    return repo, ws, runtime, backup, sha, env


def _run(staging, *args):
    repo, _ws, _runtime, _backup, _sha, env = staging
    return _cmd(["bash", str(SCRIPT), *args], cwd=repo, env=env)


def test_default_dry_run_never_mutates_runtime_or_creates_backups(staging):
    _, _, runtime, backup, sha, _ = staging
    res = _run(staging)
    assert res.returncode == 0, res.stderr
    assert "DRY_RUN_OK" in res.stdout
    assert f"SOURCE_SHA={sha}" in res.stdout
    assert "SOURCE = 'old'" in (runtime / "inneros_core_runtime" / "dev_swarm_scheduler.py").read_text()
    assert not backup.exists()


def test_apply_requires_explicit_exact_sha(staging):
    _, _, runtime, backup, _, _ = staging
    assert _run(staging, "--apply").returncode != 0
    assert _run(staging, "--apply", "--expected-sha", "f" * 40).returncode != 0
    assert "SOURCE = 'old'" in (runtime / "inneros_core_runtime" / "dev_swarm_scheduler.py").read_text()
    assert not backup.exists()


def test_apply_creates_backup_and_preserves_local_runtime_env(staging):
    _, _, runtime, backup, sha, _ = staging
    (runtime / "inneros_core_runtime" / ".env").write_text("LOCAL=stay\n")
    result = _run(staging, "--apply", "--expected-sha", sha)
    assert result.returncode == 0, result.stderr
    assert "SYNC_OK SHA=" + sha in result.stdout
    assert "SOURCE = 'approved'" in (runtime / "inneros_core_runtime" / "dev_swarm_scheduler.py").read_text()
    assert (runtime / "inneros_core_runtime" / ".env").read_text() == "LOCAL=stay\n"
    assert list(backup.glob("runtime-before-*.tar.gz")), "Expected a durable runtime backup"


def test_apply_rejects_dirty_tracked_release_sources(staging):
    _, ws, runtime, backup, sha, _ = staging
    (ws / "scripts" / "inneros_coordination_cycle.py").write_text("UNCOMMITTED=1\n")
    result = _run(staging, "--apply", "--expected-sha", sha)
    assert result.returncode != 0
    assert "uncommitted tracked changes" in result.stderr
    assert "VERSION = 1" in (runtime / "scripts" / "inneros_coordination_cycle.py").read_text()
    assert not backup.exists()
