"""Regression coverage for the shared InnerOS executor evidence contract."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from inneros_core_runtime.execution_receipts import committed_objective_receipt, git_head


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


if __name__ == "__main__":
    unittest.main()
