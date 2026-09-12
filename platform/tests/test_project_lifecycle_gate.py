from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

import inneros_core_runtime.integration_guardian as guardian
import inneros_core_runtime.project_git_alignment as project_git_alignment


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _seed_remote(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.name", "Lifecycle Test")
    _git(seed, "config", "user.email", "lifecycle@example.invalid")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-u", "origin", "main")
    return origin, seed


def _clone(origin: Path, path: Path, branch: str = "main") -> Path:
    subprocess.run(["git", "clone", "-b", branch, str(origin), str(path)], check=True, capture_output=True, text=True)
    _git(path, "config", "user.name", "Lifecycle Test")
    _git(path, "config", "user.email", "lifecycle@example.invalid")
    return path


def _worker(worktree: Path, head: str, target: str = "main") -> dict:
    return {
        "task_id": "ops_lifecycle_test",
        "launch": {
            "worktree": {"worktree": str(worktree)},
            "plan": {"requested_base_ref": target},
        },
        "executor": {
            "status": "executed",
            "outcome": "PASS",
            "test_status": "PASS",
            "files_touched": ["feature.txt"],
            "implementation_writes_product": ["feature.txt"],
            "commit": {"head": head},
        },
    }


def test_canonical_target_defaults_feature_work_to_main(tmp_path: Path) -> None:
    worker = _worker(tmp_path, "abc1234", "feature/temporary")
    assert guardian._canonical_target(worker) == "main"
    worker["launch"]["plan"]["requested_base_ref"] = "origin/main"
    assert guardian._canonical_target(worker) == "main"
    worker["launch"]["plan"]["requested_base_ref"] = "hackathon/assemblyai-2026"
    assert guardian._canonical_target(worker) == "hackathon/assemblyai-2026"


def test_integration_gate_fast_forwards_main_without_force(tmp_path: Path) -> None:
    origin, _seed = _seed_remote(tmp_path)
    work = _clone(origin, tmp_path / "work")
    (work / "feature.txt").write_text("integrated\n", encoding="utf-8")
    _git(work, "add", "feature.txt")
    _git(work, "commit", "-m", "feature")
    expected = _git(work, "rev-parse", "HEAD")

    result = guardian._integration_gate(_worker(work, expected), expected)

    assert result["ok"] is True
    assert result["status"] == "integrated"
    assert result["force_push"] is False
    assert result["target"] == "main"
    assert _git(origin, "rev-parse", "refs/heads/main") == expected


def test_integration_gate_refuses_divergent_main(tmp_path: Path) -> None:
    origin, seed = _seed_remote(tmp_path)
    work = _clone(origin, tmp_path / "work")
    (work / "feature.txt").write_text("local\n", encoding="utf-8")
    _git(work, "add", "feature.txt")
    _git(work, "commit", "-m", "local feature")
    expected = _git(work, "rev-parse", "HEAD")

    (seed / "remote.txt").write_text("remote advanced\n", encoding="utf-8")
    _git(seed, "add", "remote.txt")
    _git(seed, "commit", "-m", "remote advance")
    remote_expected = _git(seed, "rev-parse", "HEAD")
    _git(seed, "push", "origin", "main")

    result = guardian._integration_gate(_worker(work, expected), expected)

    assert result["ok"] is False
    assert result["status"] == "merge_required"
    assert result["reason"] == "canonical_target_advanced_or_diverged"
    assert _git(origin, "rev-parse", "refs/heads/main") == remote_expected


def test_integration_gate_refuses_dirty_worktree(tmp_path: Path) -> None:
    origin, _seed = _seed_remote(tmp_path)
    work = _clone(origin, tmp_path / "work")
    (work / "feature.txt").write_text("committed\n", encoding="utf-8")
    _git(work, "add", "feature.txt")
    _git(work, "commit", "-m", "feature")
    expected = _git(work, "rev-parse", "HEAD")
    (work / "feature.txt").write_text("dirty\n", encoding="utf-8")

    result = guardian._integration_gate(_worker(work, expected), expected)

    assert result["ok"] is False
    assert result["reason"] == "worktree_dirty_after_verification"


def test_hackathon_target_stays_isolated_from_main(tmp_path: Path) -> None:
    origin, seed = _seed_remote(tmp_path)
    main_before = _git(seed, "rev-parse", "HEAD")
    _git(seed, "checkout", "-b", "hackathon/assemblyai-2026")
    _git(seed, "push", "-u", "origin", "hackathon/assemblyai-2026")
    work = _clone(origin, tmp_path / "work", "hackathon/assemblyai-2026")
    (work / "feature.txt").write_text("contest delta\n", encoding="utf-8")
    _git(work, "add", "feature.txt")
    _git(work, "commit", "-m", "hackathon delta")
    expected = _git(work, "rev-parse", "HEAD")

    result = guardian._integration_gate(_worker(work, expected, "hackathon/assemblyai-2026"), expected)

    assert result["ok"] is True
    assert result["target_type"] == "hackathon"
    assert result["auto_promotes_to_main"] is False
    assert _git(origin, "rev-parse", "refs/heads/hackathon/assemblyai-2026") == expected
    assert _git(origin, "rev-parse", "refs/heads/main") == main_before


def test_project_git_alignment_reports_clean_same_sha(tmp_path: Path, monkeypatch) -> None:
    responses = {
        ("branch", "--show-current"): (0, "main\n"),
        ("rev-parse", "HEAD"): (0, "abc123\n"),
        ("rev-parse", "--verify", "origin/main^{commit}"): (0, "abc123\n"),
        ("status", "--porcelain"): (0, ""),
        ("remote", "get-url", "origin"): (0, "https://github.com/Rafa-Innerchispa/demo.git\n"),
    }

    def fake_probe(_path: Path, args: list[str], timeout: int = 15):
        rc, out = responses[tuple(args)]
        return subprocess.CompletedProcess(["git", *args], rc, stdout=out, stderr="")

    monkeypatch.setattr(project_git_alignment, "_probe", fake_probe)
    checkout = tmp_path / "demo"
    (checkout / ".git").mkdir(parents=True)
    result = project_git_alignment.alignment_status(str(checkout), "Rafa-Innerchispa/demo")

    assert result["ok"] is True
    assert result["aligned_with_origin_main"] is True
    assert result["reason"] == "aligned"


class _Cursor(list):
    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, value: int):
        return _Cursor(self[:value])


class _Collection:
    def __init__(self, workers: list[dict]):
        self.workers = workers
        self.updates: list[tuple[dict, dict]] = []

    def find(self, *_args, **_kwargs):
        return _Cursor(self.workers)

    def update_one(self, query: dict, update: dict):
        self.updates.append((query, update))
        return Mock(modified_count=1)


class _DB(dict):
    def __init__(self, worker: dict):
        super().__init__({guardian.WORKERS_COL: _Collection([worker])})


def test_guardian_never_completes_before_canonical_integration(tmp_path: Path) -> None:
    worker = _worker(tmp_path, "abc1234")
    worker["status"] = "verification"
    db = _DB(worker)
    verdict = {
        "ok": True,
        "task_id": worker["task_id"],
        "test_status": "PASS",
        "files_touched": ["feature.txt"],
        "product_files": ["feature.txt"],
        "expected_head": "abc1234",
        "observed_head": "abc1234",
        "canonical_target": "main",
        "reasons": [],
    }
    pending = {"ok": False, "status": "merge_required", "reason": "canonical_target_advanced_or_diverged"}

    with patch.object(guardian, "verify_worker", return_value=verdict), \
         patch.object(guardian, "_integration_gate", return_value=pending), \
         patch.object(guardian.coordination_live, "update_ops_task_state") as transition, \
         patch.object(guardian.coordination_live, "heartbeat_ops_task"):
        result = guardian.guardian_tick(db=db)

    assert result["ok"] is False
    completed_calls = [call for call in transition.call_args_list if len(call.args) > 1 and call.args[1] == "completed"]
    assert completed_calls == []
    assert db[guardian.WORKERS_COL].updates[-1][1]["$set"]["guardian.status"] == "INTEGRATION_PENDING"
