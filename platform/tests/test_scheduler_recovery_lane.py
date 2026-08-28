from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import dev_swarm_recovery, dev_swarm_scheduler


class SchedulerRecoveryLaneTests(unittest.TestCase):
    def test_recovery_lane_dry_run_selects_retryable_blocked_task(self):
        task = {
            "task_id": "ops_recovery",
            "status": "blocked",
            "owner": "dev_swarm",
            "assignee": "ralfia",
            "priority": "p0",
            "title": "InnerOS scheduler repair",
            "checklist": ["Repo explícito: Rafa-Innerchispa/innerops-agentic-platform."],
            "dev_swarm_retry_requested": True,
        }
        fake_db = mock.MagicMock()
        fake_db.__getitem__.return_value.find.return_value.sort.return_value.limit.return_value = [task]
        with mock.patch.object(dev_swarm_scheduler, "_db", return_value=fake_db), mock.patch.object(
            dev_swarm_scheduler,
            "reconcile_capacity_state",
            return_value={"ok": True, "reason": "recovery_lane"},
        ), mock.patch.object(
            dev_swarm_scheduler,
            "capacity_status",
            return_value={
                "recommendation": {"admittable_now": 2},
                "workers": {"active_worker_count": 0},
            },
        ), mock.patch.object(
            dev_swarm_scheduler.local_execution_plane,
            "repo_policy_status",
            return_value={"ok": True, "write_scope": "worktree"},
        ):
            result = dev_swarm_recovery.scheduler_recovery_tick(dry_run=True, limit=3)

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["lane"], "scheduler_recovery")
        self.assertEqual(len(result["selected"]), 1)
        self.assertEqual(result["selected"][0]["task_id"], "ops_recovery")

    def test_recovery_lane_skips_when_gpu_budget_zero(self):
        task = {
            "task_id": "ops_recovery",
            "status": "blocked",
            "owner": "dev_swarm",
            "assignee": "ralfia",
            "priority": "p0",
            "title": "InnerOS scheduler repair",
            "checklist": ["Repo explícito: Rafa-Innerchispa/innerops-agentic-platform."],
            "dev_swarm_retry_requested": True,
        }
        fake_db = mock.MagicMock()
        fake_db.__getitem__.return_value.find.return_value.sort.return_value.limit.return_value = [task]
        with mock.patch.object(dev_swarm_scheduler, "_db", return_value=fake_db), mock.patch.object(
            dev_swarm_scheduler,
            "reconcile_capacity_state",
            return_value={"ok": True, "reason": "recovery_lane"},
        ), mock.patch.object(
            dev_swarm_scheduler,
            "capacity_status",
            return_value={
                "recommendation": {"admittable_now": 0},
                "workers": {"active_worker_count": 4},
            },
        ), mock.patch.object(
            dev_swarm_scheduler.local_execution_plane,
            "repo_policy_status",
            return_value={"ok": True, "write_scope": "worktree"},
        ), mock.patch.object(dev_swarm_scheduler, "fanout_execute") as fanout:
            result = dev_swarm_recovery.scheduler_recovery_tick(dry_run=False, limit=3)

        fanout.assert_not_called()
        self.assertEqual(result["selected"], [])
        self.assertTrue(any(row.get("reason") == "gpu_capacity_zero" for row in result["skipped"]))


if __name__ == "__main__":
    unittest.main()
