"""Offline tests for Temporal → bounded executor bridge."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from inneros_core_runtime import temporal_bounded_executor as tbe


class TemporalBoundedExecutorTests(unittest.TestCase):
    def test_default_work_branch_is_generated(self) -> None:
        branch = tbe.default_work_branch({"task_id": "ops_187da9289132"})
        self.assertTrue(branch.startswith("local-agent/temporal-"))

    def test_sync_bridge_artifacts_copies_known_files(self) -> None:
        with TemporaryDirectory() as tmp:
            wt = Path(tmp)
            with patch.object(tbe, "CANONICAL_PLATFORM_ROOT", Path(__file__).resolve().parents[1]):
                touched = tbe.sync_bridge_artifacts(wt)
            self.assertTrue(any("temporal_bounded_executor.py" in path for path in touched))

    def test_run_bounded_executor_uses_allowlisted_command(self) -> None:
        envelope = {
            "task_id": "ops_bridge_canary",
            "correlation_id": "corr-bridge",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "task_class": "coding",
            "assignee": "dev_swarm",
            "base_ref": "main",
        }
        fake_wt = "/tmp/fake-worktree"
        with (
            patch.object(tbe, "_ensure_repo_worktree", return_value=Path(fake_wt)),
            patch.object(tbe, "sync_bridge_artifacts", return_value=["platform/inneros_core_runtime/temporal_activities.py"]),
            patch.object(
                tbe,
                "_git_diff_summary",
                return_value=(1, "+ src/product.py", ["src/product.py"]),
            ),
            patch(
                "inneros_core_runtime.local_execution_plane.run_command_allowlisted",
                return_value={
                    "ok": True,
                    "command_result": {"ok": True, "returncode": 0, "stdout": "1 passed"},
                },
            ) as run_cmd,
        ):
            result = tbe.run_bounded_executor(envelope, fake_wt, {"response": "plan"})
        self.assertFalse(result.get("candidate_only"))
        self.assertFalse(result.get("requires_bounded_executor"))
        self.assertTrue(result.get("ok"))
        self.assertEqual(result["test_results"]["exit_code"], 0)
        run_cmd.assert_called_once()


    def test_bridge_artifacts_do_not_count_as_product_changes(self) -> None:
        envelope = {
            "task_id": "ops_bridge_only",
            "correlation_id": "corr-bridge-only",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "task_class": "coding",
            "assignee": "dev_swarm",
            "base_ref": "main",
        }
        fake_wt = "/tmp/fake-worktree"
        bridge = ["platform/inneros_core_runtime/temporal_activities.py"]
        with (
            patch.object(tbe, "_ensure_repo_worktree", return_value=Path(fake_wt)),
            patch.object(tbe, "sync_bridge_artifacts", return_value=bridge),
            patch.object(tbe, "_git_diff_summary", return_value=(0, "", [])) as diff_summary,
            patch(
                "inneros_core_runtime.local_execution_plane.run_command_allowlisted",
                return_value={
                    "ok": True,
                    "command_result": {"ok": True, "returncode": 0, "stdout": "3 passed"},
                },
            ),
        ):
            result = tbe.run_bounded_executor(envelope, fake_wt, {"response": "generic plan"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["files_count"], 0)
        self.assertEqual(result["execution_evidence"]["changed_paths"], [])
        self.assertEqual(result["execution_evidence"]["bridge_artifacts"], bridge)
        self.assertEqual(
            result["test_results"]["reason"],
            "coding_task_requires_product_diff_or_files",
        )
        diff_summary.assert_called_once_with(Path(fake_wt), exclude_paths=bridge)

    def test_execution_evidence_records_authoritative_command(self) -> None:
        envelope = {
            "task_id": "ops_product_change",
            "correlation_id": "corr-product",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "task_class": "coding",
            "assignee": "dev_swarm",
            "base_ref": "main",
            "verify_command": ["python3", "-m", "pytest", "tests/test_product.py", "-q"],
        }
        fake_wt = "/tmp/fake-worktree"
        with (
            patch.object(tbe, "_ensure_repo_worktree", return_value=Path(fake_wt)),
            patch.object(tbe, "sync_bridge_artifacts", return_value=[]),
            patch.object(tbe, "_git_diff_summary", return_value=(1, "+ src/product.py", ["src/product.py"])),
            patch(
                "inneros_core_runtime.local_execution_plane.run_command_allowlisted",
                return_value={
                    "ok": True,
                    "command_run_id": "cmd-123",
                    "command_result": {"ok": True, "returncode": 0, "stdout": "1 passed"},
                },
            ),
        ):
            result = tbe.run_bounded_executor(envelope, fake_wt, {"response": "done"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["execution_evidence"]["changed_paths"], ["src/product.py"])
        self.assertEqual(
            result["execution_evidence"]["executed_commands"][0]["argv"],
            envelope["verify_command"],
        )
        self.assertEqual(
            result["execution_evidence"]["executed_commands"][0]["command_run_id"],
            "cmd-123",
        )


if __name__ == "__main__":
    unittest.main()
