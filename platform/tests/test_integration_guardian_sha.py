"""Commit identity regression: short executor SHAs must resolve uniquely.

Integration Guardian must fail closed on ambiguous or different commits, while
allowing the same commit in its abbreviated and full forms.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import integration_guardian as ig

COMMIT_FULL = "03d94807a8ce2a5fdee5c1678c32e37e9e6b3ec0"
DIFFERENT_FULL = "a3d94807a8ce2a5fdee5c1678c32e37e9e6b3ec0"


def _worker(worktree, expected="03d94807"):
    return {
        "task_id": "ops_6113b4f0abf7",
        "launch": {"worktree": {"worktree": str(worktree)}},
        "executor": {
            "status": "executed",
            "outcome": "PASS",
            "test_status": "PASS",
            "files_touched": ["src/gitlab_mr_verifier.py", "tests/test_gitlab_mr_verifier.py"],
            "implementation_writes_product": ["src/gitlab_mr_verifier.py"],
            "commit": {"head": expected},
        },
    }


def test_abbreviated_sha_resolves_to_verified_full_commit(tmp_path):
    calls = []

    def git(argv, cwd, timeout_seconds=30):
        calls.append(argv)
        if argv == ["git", "rev-parse", "HEAD"]:
            return {"ok": True, "stdout": COMMIT_FULL + "\n"}
        if argv == ["git", "rev-parse", "--verify", "03d94807^{commit}"]:
            return {"ok": True, "stdout": COMMIT_FULL + "\n"}
        raise AssertionError(f"unexpected git call: {argv!r}")

    with mock.patch.object(ig.local_execution_plane, "_run", side_effect=git):
        verdict = ig.verify_worker(_worker(tmp_path))
    assert verdict["ok"] is True
    assert verdict["expected_head"] == "03d94807"
    assert verdict["observed_head"] == COMMIT_FULL
    assert len(calls) == 2


def test_abbreviated_sha_for_different_commit_is_rejected(tmp_path):
    def git(argv, cwd, timeout_seconds=30):
        if argv == ["git", "rev-parse", "HEAD"]:
            return {"ok": True, "stdout": COMMIT_FULL}
        return {"ok": True, "stdout": DIFFERENT_FULL}

    with mock.patch.object(ig.local_execution_plane, "_run", side_effect=git):
        verdict = ig.verify_worker(_worker(tmp_path))
    assert verdict["ok"] is False
    assert "commit_head_mismatch" in verdict["reasons"]


def test_ambiguous_abbreviated_sha_fails_closed(tmp_path):
    def git(argv, cwd, timeout_seconds=30):
        if argv == ["git", "rev-parse", "HEAD"]:
            return {"ok": True, "stdout": COMMIT_FULL}
        return {"ok": False, "stderr": "short object ID is ambiguous", "stdout": ""}

    with mock.patch.object(ig.local_execution_plane, "_run", side_effect=git):
        verdict = ig.verify_worker(_worker(tmp_path))
    assert verdict["ok"] is False
    assert "expected_commit_sha_unresolvable" in verdict["reasons"]


def test_symbolic_or_invalid_expected_sha_is_never_accepted(tmp_path):
    with mock.patch.object(
        ig.local_execution_plane,
        "_run",
        return_value={"ok": True, "stdout": COMMIT_FULL},
    ) as run:
        verdict = ig.verify_worker(_worker(tmp_path, expected="main"))
    assert verdict["ok"] is False
    assert "expected_commit_sha_invalid" in verdict["reasons"]
    run.assert_called_once()


def test_full_sha_uses_verified_git_object_resolution(tmp_path):
    def git(argv, cwd, timeout_seconds=30):
        return {"ok": True, "stdout": COMMIT_FULL}

    with mock.patch.object(ig.local_execution_plane, "_run", side_effect=git):
        verdict = ig.verify_worker(_worker(tmp_path, expected=COMMIT_FULL))
    assert verdict["ok"] is True
