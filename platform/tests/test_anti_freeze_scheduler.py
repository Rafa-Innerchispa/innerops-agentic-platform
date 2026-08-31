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

    def test_blocked_task_is_not_retryable_without_explicit_retry_flag(self):
        task = {
            "task_id": "ops_dead",
            "status": "blocked",
            "owner": "dev_swarm",
            "assignee": "ralfia",
            "priority": "p0",
            "title": "InnerOS scheduler repair",
            "checklist": ["Repo explícito: Rafa-Innerchispa/innerops-agentic-platform.", "Implement scheduler truth fixes."],
        }
        ok, reason, _repo = dev_swarm_scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "ops_status_blocked_no_auto_retry")

    def test_failed_retryable_task_requires_explicit_retry_flag_and_policy(self):
        task = {
            "task_id": "ops_retry",
            "status": "blocked",
            "owner": "dev_swarm",
            "assignee": "ralfia",
            "priority": "p0",
            "title": "InnerOS scheduler repair",
            "checklist": ["Repo explícito: Rafa-Innerchispa/innerops-agentic-platform.", "Implement scheduler truth fixes."],
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
