from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import dev_swarm_scheduler


class AntiFreezeSchedulerTests(unittest.TestCase):
    def test_heartbeat_does_not_count_as_progress(self):
        worker = {
            "created_at": "2026-08-27T10:00:00+00:00",
            "started_at": "2026-08-27T10:01:00+00:00",
            "last_heartbeat_at": "2026-08-27T20:00:00+00:00",
            "updated_at": "2026-08-27T20:00:00+00:00",
            "executor": {
                "last_progress_at": "2026-08-27T10:05:00+00:00",
                "updated_at": "2026-08-27T20:00:00+00:00",
            },
        }
        observed = dev_swarm_scheduler._worker_progress_time(worker)
        self.assertEqual(observed, datetime(2026, 8, 27, 10, 5, tzinfo=timezone.utc))

    def test_stale_external_claim_is_never_blocked_by_swarm(self):
        now = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
        task = {
            "task_id": "ops_claim_1",
            "status": "in_progress",
            "owner": "cursor",
            "claimed_by": "cursor",
            "claim_token": "original",
            "lease_until": "2026-10-12T18:00:00+00:00",
            "updated_at": "2026-10-11T00:00:00+00:00",
        }
        result = mock.Mock()
        result.modified_count = 0
        col = mock.Mock()
        col.find.return_value.limit.return_value = [task]
        db = mock.MagicMock()
        db.__getitem__.return_value = col
        changed = dev_swarm_scheduler._reconcile_stale_ops_tasks(
            db, now, now.isoformat(), "test"
        )
        self.assertEqual(changed, 0)
        col.update_one.assert_not_called()

    def test_expired_repo_lock_preserved_for_external_claim(self):
        now = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
        lock = {"resource_id": "inneros", "task_id": "ops_claim",
                "status": "active", "expires_at": "2026-10-12T18:00:00+00:00"}
        task = {"task_id": "ops_claim", "status": "claimed",
                "owner": "cursor", "claim_token": "original",
                "lease_until": "2026-10-12T18:00:00+00:00"}
        db = mock.MagicMock()
        locks = mock.Mock()
        locks.find.return_value = [lock]
        tasks = mock.Mock()
        tasks.find_one.return_value = task
        def get_collection(name):
            return locks if name == "ralfia_coordination_locks" else tasks
        db.__getitem__.side_effect = get_collection
        result = dev_swarm_scheduler._expire_inactive_locks(db, now, now.isoformat())
        self.assertEqual(result["preserved_active"], 1)
        self.assertEqual(result["expired"], 0)
        locks.update_one.assert_not_called()

    def test_blocked_task_is_not_retryable_without_explicit_retry_flag(self):
        task = {
            "task_id": "ops_dead",
            "status": "blocked",
            "owner": "dev_swarm",
            "assignee": "ralfia",
            "priority": "p0",
            "title": "InnerOS scheduler repair",
            "checklist": ["Repo explícito: Rafa-Innerchispa/innerops-agentic-platform."],
        }
        ok, reason, _repo = dev_swarm_scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "status_not_proposed")

    def test_failed_retryable_task_requires_explicit_retry_flag_and_policy(self):
        task = {
            "task_id": "ops_retry",
            "status": "blocked",
            "owner": "dev_swarm",
            "assignee": "ralfia",
            "priority": "p0",
            "title": "InnerOS scheduler repair",
            "checklist": ["Repo explícito: Rafa-Innerchispa/innerops-agentic-platform."],
            "dev_swarm_retry_requested": True,
        }
        with mock.patch.object(
            dev_swarm_scheduler.local_execution_plane,
            "repo_policy_status",
            return_value={"ok": True, "write_scope": "worktree"},
        ):
            ok, reason, repo = dev_swarm_scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, dev_swarm_scheduler.SAFE_INNEROS_REPO)


if __name__ == "__main__":
    unittest.main()
