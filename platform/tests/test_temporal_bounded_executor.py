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
            patch.object(tbe, "_git_diff_summary", return_value=(1, "+ platform/inneros_core_runtime/temporal_activities.py")),
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
        self.assertFalse(result.get("ok"))
        self.assertEqual(result["test_results"]["exit_code"], 0)
        self.assertEqual(
            result["test_results"].get("reason"),
            "candidate_not_materialized_into_real_repo_writes",
        )
        self.assertEqual(result["bounded_executor"]["artifacts_synced"], [])
        run_cmd.assert_called_once()


if __name__ == "__main__":
    unittest.main()
