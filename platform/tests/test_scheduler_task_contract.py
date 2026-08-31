from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from inneros_core_runtime import google_adk_a2a, scheduler_task_contract
from raphiia_openai import dev_swarm_scheduler as scheduler


class SchedulerTaskContractTests(unittest.TestCase):
    def test_read_only_task_from_checklist_is_detected(self) -> None:
        task = {
            "task_id": "ops_readonly",
            "title": "P0 Judge deploy readiness + acceptance prep",
            "checklist": [
                "READ-ONLY / NO source edits mientras Antigravity aplica UX.",
                "Repo Rafa-Innerchispa/innerspark-workforce-ai y runtime AMD .5 solamente para inspección.",
            ],
        }
        self.assertEqual(scheduler_task_contract.task_mode(task), "read_only")
        self.assertFalse(scheduler_task_contract.requires_product_writes("verify deploy readiness", task))

    def test_repo_only_label_wins_over_workforce_noise(self) -> None:
        task = {
            "task_id": "ops_platform_only",
            "checklist": [
                "Repo ONLY: Rafa-Innerchispa/innerops-agentic-platform. Do NOT touch Workforce/Judge files.",
                "Fix scheduler/executor classification for QA verify tasks.",
            ],
        }
        repo = scheduler_task_contract.explicit_repo_from_labels(task, canonical_hints=scheduler.CANONICAL_REPO_HINTS)
        self.assertEqual(repo, scheduler.SAFE_INNEROS_REPO)
        with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "worktree"}):
            ok, reason, inferred = scheduler._eligible_reason({**task, "status": "proposed", "assignee": "cursor", "priority": "p0"})
        self.assertTrue(ok)
        self.assertEqual(inferred, scheduler.SAFE_INNEROS_REPO)

    def test_read_only_task_is_not_swarm_eligible(self) -> None:
        task = {
            "task_id": "ops_verify_only",
            "status": "proposed",
            "assignee": "cursor",
            "priority": "p0",
            "task_mode": "read_only",
            "title": "Verify Judge trace contract",
            "checklist": ["Evidence-only verification, no source writes."],
        }
        with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "worktree"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "read_only_task_not_swarm_write_eligible")

    def test_ops_liveness_expired_without_worker_token(self) -> None:
        now = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)
        task = {
            "status": "in_progress",
            "started_at": "2026-08-31T18:00:00+00:00",
            "last_heartbeat_at": None,
        }
        self.assertTrue(scheduler_task_contract.ops_liveness_expired(task, stale_seconds=1800, now=now))

    def test_ops_liveness_not_expired_with_fresh_heartbeat(self) -> None:
        now = datetime(2026, 8, 31, 18, 10, tzinfo=timezone.utc)
        task = {
            "status": "in_progress",
            "worker_token": "worker_abc",
            "last_heartbeat_at": "2026-08-31T18:09:00+00:00",
        }
        self.assertFalse(scheduler_task_contract.ops_liveness_expired(task, stale_seconds=1800, now=now))


class IdeBridgeRunningTruthTests(unittest.TestCase):
    def test_in_progress_without_worker_is_not_running(self) -> None:
        projected = google_adk_a2a.project_ide_task_bridge(
            a2a_status={"status": {"state": "submitted"}, "ops_status": "in_progress"},
            target="cursor",
        )
        self.assertEqual(projected["execution_state"], "delivered_to_inbox")
        self.assertFalse(projected["running"])

    def test_in_progress_with_worker_token_is_running(self) -> None:
        projected = google_adk_a2a.project_ide_task_bridge(
            a2a_status={"status": {"state": "working"}, "ops_status": "in_progress", "worker_token": "worker_1"},
            target="cursor",
        )
        self.assertEqual(projected["execution_state"], "running")
        self.assertTrue(projected["running"])


if __name__ == "__main__":
    unittest.main()
