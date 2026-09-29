from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


def _git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def test_blocked_missing_task_binding_rejected_before_proposed() -> None:
    """A development task with no resolvable repo must be rejected before entering proposed."""
    from inneros_core_runtime import coordination_live

    # Missing repo and non-inferrable context
    result = coordination_live.create_ops_task(
        assignee="codex",
        title="Implement feature without any repo or project hint",
        checklist=["Write code and add endpoints"],
        task_class="coding",
        execution_lane="local_dev_swarm",
    )
    assert result["ok"] is False
    assert "blocked_missing_task_binding" in result["error"]
    assert result["executable"] is False
    assert "missing_repo_binding" in result["blockers"]


def test_dev_task_auto_enriches_from_project_registry() -> None:
    """When a project ID or short name is unambiguous, automatically enrich repo binding."""
    from inneros_core_runtime import coordination_live

    with mock.patch("raphiia_openai.mongo_store.get_db") as mock_db_getter:
        mock_coll = mock.MagicMock()
        mock_coll.find_one.return_value = None
        mock_state = mock.MagicMock()
        mock_state.find_one.return_value = {"revision": 1}
        mock_msg = mock.MagicMock()
        mock_log = mock.MagicMock()
        mock_db = {
            "ralfia_ops_tasks": mock_coll,
            "ralfia_coordination_state": mock_state,
            "ralfia_agent_messages": mock_msg,
            "ralfia_coordination_log": mock_log,
        }
        mock_db_getter.return_value = mock_db

        with mock.patch("inneros_core_runtime.coordination_live._publish_task_event"):
            with mock.patch("raphiia_openai.memory.agent_messages.create_agent_message"):
                result = coordination_live.create_ops_task(
                    assignee="antigravity",
                    title="Implement VoiceOps SIP Audio Bridge",
                    checklist=["Build SIP parser"],
                    project_id="inneros-voiceops-assemblyai",
                )

        assert result["ok"] is True
        doc = mock_coll.insert_one.call_args[0][0]
        assert doc["repo"] == "Rafa-Innerchispa/inneros-voiceops-assemblyai"
        assert doc["base_ref"] == "main"
        assert doc["task_class"] == "coding"
        assert doc["execution_lane"] == "local_dev_swarm"
        assert doc["runtime_profile"] == "python-tests"
        assert doc["execution_policy"] == "local-first-no-external-spend"


def test_task_executability_preflight_reports_exact_blockers() -> None:
    """Executability preflight returns executable=True/False with exact blockers."""
    from inneros_core_runtime import dev_swarm_scheduler

    # 1. Missing binding task -> Not executable
    bad_task = {
        "task_id": "ops_missing_binding",
        "status": "proposed",
        "assignee": "codex",
        "title": "Unbound code repair",
        "checklist": ["Fix bugs in code"],
        "task_class": "coding",
    }
    preflight_bad = dev_swarm_scheduler.task_executability_preflight(bad_task)
    assert preflight_bad["executable"] is False
    assert "blocked_missing_task_binding" in preflight_bad["blockers"]

    # 2. Bound valid task -> Executable
    good_task = {
        "task_id": "ops_good_binding",
        "status": "proposed",
        "assignee": "codex",
        "title": "VoiceOps AssemblyAI SIP/RTP bridge",
        "checklist": ["Implement SIP parser and RTP audio bridge"],
        "related_project": "inneros-voiceops-assemblyai",
        "execution_lane": "local_dev_swarm",
        "priority": "p0",
    }
    with mock.patch.object(dev_swarm_scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
        preflight_good = dev_swarm_scheduler.task_executability_preflight(good_task)
        assert preflight_good["executable"] is True
        assert preflight_good["repo"] == "Rafa-Innerchispa/inneros-voiceops-assemblyai"
        assert preflight_good["resolved_binding"]["base_ref"] == "main"
        assert preflight_good["resolved_binding"]["execution_lane"] == "local_dev_swarm"


def test_prepare_repo_existing_non_empty_repo_safe_reuse(tmp_path: Path, monkeypatch) -> None:
    """An existing, valid git repo is safely fetched and refreshed without attempting git clone over it."""
    from inneros_core_runtime import local_execution_plane as lep

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(["init", "-b", "main"], seed)
    _git(["config", "user.name", "Test"], seed)
    _git(["config", "user.email", "test@example.invalid"], seed)
    (seed / "README.md").write_text("initial main\n", encoding="utf-8")
    _git(["add", "README.md"], seed)
    _git(["commit", "-m", "seed main"], seed)

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(seed), str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )

    # Existing local repo already cloned from remote
    source = tmp_path / "existing_repo"
    subprocess.run(
        ["git", "clone", str(remote), str(source)],
        check=True,
        capture_output=True,
        text=True,
    )

    # Link seed to remote
    _git(["remote", "add", "origin", str(remote)], seed)

    # Push new commit to remote via seed
    (seed / "updated.txt").write_text("new content\n", encoding="utf-8")
    _git(["add", "updated.txt"], seed)
    _git(["commit", "-m", "update from remote"], seed)
    _git(["push", "origin", "main"], seed)

    conf = {
        "profile": "python-tests",
        "source_path": str(source),
        "allowed_paths": ["."],
        "package_roots": ["."],
        "worktrees_path": str(tmp_path / "worktrees"),
    }
    monkeypatch.setattr(lep, "_repo_config", lambda repo: conf)

    result = lep.prepare_repo(
        repo="Rafa-Innerchispa/innerops-agentic-platform",
        base_ref="main",
        actor="antigravity",
        task_id="ops_test_reuse",
        correlation_id="corr-test-reuse",
        idempotency_key="idem-test-reuse",
    )

    assert result["ok"] is True
    assert result["idempotent"] is True
    assert "clone" not in result  # Proves git clone was NOT executed
    assert (source / "updated.txt").read_text(encoding="utf-8") == "new content\n"


def test_prepare_repo_non_empty_non_git_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """When source_path exists, is non-empty, and is NOT a git repo, fail closed with an actionable error."""
    from inneros_core_runtime import local_execution_plane as lep

    source = tmp_path / "non_git_dir"
    source.mkdir()
    (source / "some_file.txt").write_text("not a git repo", encoding="utf-8")

    conf = {
        "profile": "python-tests",
        "source_path": str(source),
        "allowed_paths": ["."],
        "package_roots": ["."],
        "worktrees_path": str(tmp_path / "worktrees"),
    }
    monkeypatch.setattr(lep, "_repo_config", lambda repo: conf)

    result = lep.prepare_repo(
        repo="Rafa-Innerchispa/inneros",
        base_ref="main",
        actor="antigravity",
        task_id="ops_test_fail_closed",
        correlation_id="corr-test-fail",
        idempotency_key="idem-test-fail",
    )

    assert result["ok"] is False
    assert "source_path_exists_and_not_empty_not_git" in result["error"]


def test_prepare_repo_mismatched_repo_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """When source_path points to a git repo of a different repository, fail closed."""
    from inneros_core_runtime import local_execution_plane as lep

    source = tmp_path / "other_repo"
    source.mkdir()
    _git(["init", "-b", "main"], source)
    _git(["config", "user.name", "Test"], source)
    _git(["config", "user.email", "test@example.invalid"], source)
    _git(["remote", "add", "origin", "https://github.com/OtherOrg/completely-different-repo.git"], source)

    conf = {
        "profile": "python-tests",
        "source_path": str(source),
        "allowed_paths": ["."],
        "package_roots": ["."],
        "worktrees_path": str(tmp_path / "worktrees"),
    }
    monkeypatch.setattr(lep, "_repo_config", lambda repo: conf)

    result = lep.prepare_repo(
        repo="Rafa-Innerchispa/inneros-voiceops",
        base_ref="main",
        actor="antigravity",
        task_id="ops_test_mismatch",
        correlation_id="corr-test-mismatch",
        idempotency_key="idem-test-mismatch",
    )

    assert result["ok"] is False
    assert "source_path_repo_mismatch" in result["error"]


def test_task_ops_bbe55083f9b4_is_executable() -> None:
    """Verifies that ops_bbe55083f9b4 (Home Audio Bus + Intelbras) is fully executable."""
    from inneros_core_runtime import dev_swarm_scheduler

    task = {
        "task_id": "ops_bbe55083f9b4",
        "correlation_id": "home-audio-bus-security-speakers-repo-bound-20260925",
        "assignee": "antigravity",
        "title": "Home Audio Bus + Intelbras (repo-bound)",
        "checklist": [
            "Implementar en Rafa-Innerchispa/inneros una capability Home Audio Bus para reproducir audio arbitrario por Home Assistant.",
        ],
        "priority": "p1",
        "status": "proposed",
        "related_project": "Rafa-Innerchispa/inneros",
        "project_id": "inneros",
        "repo": "Rafa-Innerchispa/inneros",
        "base_ref": "main",
        "task_class": "coding",
        "execution_lane": "local_dev_swarm",
        "runtime_profile": "python-tests",
        "execution_policy": "local-first-no-external-spend",
    }
    preflight = dev_swarm_scheduler.task_executability_preflight(task)
    assert preflight["executable"] is True
    assert preflight["repo"] == "Rafa-Innerchispa/inneros"
    assert preflight["resolved_binding"]["base_ref"] == "main"
    assert preflight["resolved_binding"]["task_class"] == "coding"
    assert preflight["resolved_binding"]["execution_lane"] == "local_dev_swarm"
    assert preflight["resolved_binding"]["runtime_profile"] == "python-tests"
