"""Regression coverage for the shared InnerOS executor evidence contract."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from inneros_core_runtime.execution_receipts import (
    attach_runner_test_results,
    committed_objective_receipt,
    completion_evidence_from_worktree,
    git_head,
    runner_test_results_payload,
)


class ExecutionReceiptsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "inneros-test@example.invalid")
        self.git("config", "user.name", "InnerOS contract test")
        (self.repo / "README.md").write_text("baseline\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "baseline")
        self.baseline = git_head(self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                       capture_output=True, timeout=15)

    def test_commit_with_real_file_passes(self) -> None:
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "marker.md").write_text("actual output\n", encoding="utf-8")
        self.git("add", "docs/marker.md")
        self.git("commit", "-qm", "task wrote marker")
        proof = committed_objective_receipt(self.repo, self.baseline)
        self.assertTrue(proof["ok"], proof)
        self.assertEqual(proof["objective_paths"], ["docs/marker.md"])
        self.assertEqual(proof["objective_files_count"], 1)
        self.assertNotEqual(proof["commit_sha"], self.baseline)

    def test_no_new_commit_is_not_success(self) -> None:
        proof = committed_objective_receipt(self.repo, self.baseline)
        self.assertFalse(proof["ok"])
        self.assertEqual(proof["error"], "no_new_commit_for_task")

    def test_untracked_file_is_not_objective_evidence(self) -> None:
        (self.repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        proof = committed_objective_receipt(self.repo, self.baseline)
        self.assertFalse(proof["ok"])

    def test_invalid_baseline_is_rejected(self) -> None:
        proof = committed_objective_receipt(self.repo, "--output=/tmp/unsafe")
        self.assertFalse(proof["ok"])
        self.assertEqual(proof["error"], "git_baseline_or_head_missing")

    def test_missing_paths_after_commit_fail_closed(self) -> None:
        (self.repo / "removed.txt").write_text("temporary\n", encoding="utf-8")
        self.git("add", "removed.txt")
        self.git("commit", "-qm", "added temp")
        (self.repo / "removed.txt").unlink()
        proof = committed_objective_receipt(self.repo, self.baseline)
        self.assertFalse(proof["ok"])
        self.assertEqual(proof["error"], "no_committed_objective_files")

    def test_completed_receipt_never_fabricates_test_success(self) -> None:
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "real task write")
        proof = completion_evidence_from_worktree(self.repo, self.baseline)
        self.assertTrue(proof["ok"], proof)
        self.assertNotIn("test_results", proof["evidence"])
        self.assertEqual(proof["evidence"]["objective_paths"], ["README.md"])

    def test_completed_receipt_accepts_only_explicit_exit_code(self) -> None:
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "real task write")
        good = completion_evidence_from_worktree(self.repo, self.baseline, test_exit_code=0)
        self.assertTrue(good["ok"], good)
        self.assertEqual(good["evidence"]["test_results"]["exit_code"], 0)
        failed = completion_evidence_from_worktree(self.repo, self.baseline, test_exit_code=1)
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"], "tests_failed")
        self.assertFalse(failed["evidence"]["test_results"]["ok"])
        invalid = completion_evidence_from_worktree(self.repo, self.baseline, test_exit_code="invalid")
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error"], "invalid_test_exit_code")

    def test_runner_test_results_payload_never_invents_exit_code(self) -> None:
        self.assertIsNone(runner_test_results_payload({}))
        self.assertIsNone(runner_test_results_payload({"test_results": {}}))
        nested = runner_test_results_payload(
            {"test_results": {"exit_code": 0, "ok": True, "suite": ["a.py"]}}
        )
        self.assertEqual(nested, {"exit_code": 0, "ok": True, "suite": ["a.py"]})
        flat = runner_test_results_payload({"exit_code": 2, "primary": "platform_local_pytest"})
        self.assertEqual(flat, {"exit_code": 2, "ok": False})

    def test_attach_runner_test_results_preserves_existing_when_runner_silent(self) -> None:
        base = {"commit_sha": "a" * 40, "test_results": {"exit_code": 1, "ok": False}}
        self.assertIs(attach_runner_test_results(base, None), base)


if __name__ == "__main__":
    unittest.main()
