"""Static policy gates for the trusted local release executor."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "inneros_local_release_executor.py"
WORKFLOW = ROOT / ".github" / "workflows" / "inneros-local-release.yml"


def test_local_release_is_fail_closed_and_has_rollback():
    source = SCRIPT.read_text()
    assert 'choices=("plan", "apply")' in source
    assert 'default="plan"' in source
    assert 'candidate_not_on_origin_main' in source
    assert 'checkout_sha_mismatch' in source
    assert 'dirty_candidate_checkout' in source
    assert 'approved_release_sha_not_pinned' in source
    assert 'self_hosted_runner_required' in source
    assert 'snapshot.mkdir' in source
    assert 'rollback_performed": True' in source
    assert 'os.replace(tmp, dest)' in source
    assert 'deployed_hash_mismatch' in source
    assert 'rsync' not in source
    assert 'git reset --hard' not in source
    assert 'shell=True' not in source


def test_release_workflow_does_not_use_hosted_or_pr_dispatch():
    source = WORKFLOW.read_text()
    assert "workflow_dispatch:" in source
    assert "pull_request:" not in source
    assert "self-hosted, linux, x64, inneros-amd" in source
    assert "inneros-production" in source
    assert "contents: read" in source
    assert "cancel-in-progress: false" in source
    assert "persist-credentials: false" in source
    assert "fetch-depth: 0" in source
    assert "--mode \"$RELEASE_MODE\"" in source
    assert "--restart" not in source


def _release_fixture(monkeypatch, tmp_path):
    import importlib.util
    import sys
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("inneros_release_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    repo = tmp_path / "checkout"
    runtime = tmp_path / "platform" / "inneros_core_runtime"
    backup_root = tmp_path / "backups"
    paths = [
        (repo / "platform" / "inneros_core_runtime" / rel, runtime / rel)
        for rel in module.FILES
    ] + [
        (repo / "platform" / "raphiia_openai" / rel, runtime.parent / "raphiia_openai" / rel)
        for rel in module.LIB_FILES
    ] + [
        (repo / "platform" / "scripts" / rel, runtime.parent / "scripts" / rel)
        for rel in module.SCRIPT_FILES
    ]
    for src, dest in paths:
        src.parent.mkdir(parents=True, exist_ok=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("VALUE = 2\n")
        dest.write_text("VALUE = 1\n")
    sha = "a" * 40
    module.REPO_ROOT = repo
    module.RUNTIME = runtime
    module.BACKUP_ROOT = backup_root
    monkeypatch.setattr(module, "git", lambda *args: sha if args == ("rev-parse", "HEAD") else "")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(sys, "argv", ["inneros_local_release_executor.py", "--sha", sha])
    return module, repo, runtime, backup_root, paths, sha


def test_release_plan_includes_all_coordination_and_ruby_files_without_mutation(monkeypatch, tmp_path, capsys):
    import json

    module, _, _, backup_root, paths, _ = _release_fixture(monkeypatch, tmp_path)
    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    files = {row["file"] for row in payload["files"]}
    assert {"local_execution_plane.py", "coordination_live.py", "human_task_id.py",
            "ops_task_admission.py", "dev_swarm_scheduler.py",
            "integration_guardian.py", "scripts/inneros_coordination_cycle.py",
            "raphiia_openai/local_execution_plane.py"} <= files
    assert payload["production_mutated"] is False
    assert not backup_root.exists()
    assert all(dest.read_text() == "VALUE = 1\n" for _, dest in paths)


def test_release_apply_requires_pin_and_copies_only_manifest_with_backup(monkeypatch, tmp_path, capsys):
    import json

    module, _, _, backup_root, paths, sha = _release_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(module.os, "environ", {"INNEROS_APPROVED_RELEASE": sha, "RUNNER_ENVIRONMENT": "self-hosted"})
    monkeypatch.setattr(module.sys, "argv", ["inneros_local_release_executor.py", "--sha", sha, "--mode", "apply"])
    assert module.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["production_mutated"] is True
    assert report["restarted"] is False
    assert report["rollback_performed"] is False
    assert all(dest.read_text() == "VALUE = 2\n" for _, dest in paths)
    snapshot = Path(report["snapshot"])
    assert snapshot.is_relative_to(backup_root)
    assert (snapshot / "scripts" / "inneros_coordination_cycle.py").read_text() == "VALUE = 1\n"


def test_release_restores_previous_runtime_on_midcopy_failure(monkeypatch, tmp_path):
    import pytest

    module, _, _, backup_root, paths, sha = _release_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(module.os, "environ", {"INNEROS_APPROVED_RELEASE": sha, "RUNNER_ENVIRONMENT": "self-hosted"})
    monkeypatch.setattr(module.sys, "argv", ["inneros_local_release_executor.py", "--sha", sha, "--mode", "apply"])
    original_replace = module.os.replace

    def fail_midcopy(src, dest):
        if Path(dest).name == "integration_guardian.py":
            raise OSError("simulated write failure")
        return original_replace(src, dest)

    monkeypatch.setattr(module.os, "replace", fail_midcopy)
    with pytest.raises(OSError, match="simulated write failure"):
        module.main()
    assert all(dest.read_text() == "VALUE = 1\n" for _, dest in paths)
    assert list(backup_root.iterdir())
