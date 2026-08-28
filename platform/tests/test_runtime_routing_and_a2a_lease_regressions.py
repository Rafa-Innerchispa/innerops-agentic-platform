from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import a2a_controller, dev_swarm_scheduler as scheduler


class RuntimeRoutingAndA2ALeaseRegressions(unittest.TestCase):
    def test_labelled_explicit_platform_repo_beats_negative_workforce_keyword(self) -> None:
        task = {
            "task_id": "ops_explicit_repo_in_checklist",
            "status": "proposed",
            "assignee": "ralfia",
            "priority": "critical",
            "title": "InnerOS canonical runtime source verifier",
            "checklist": [
                "Repo explícito: Rafa-Innerchispa/innerops-agentic-platform.",
                "Implementar verifier y tests del runtime canónico.",
                "No tocar Workforce, cloud ni producción externa.",
            ],
        }
        with mock.patch.object(
            scheduler.local_execution_plane,
            "repo_policy_status",
            return_value={"ok": True, "write_scope": "trusted"},
        ):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, scheduler.SAFE_INNEROS_REPO)

    def test_active_a2a_lease_is_not_claimable(self) -> None:
        now = datetime.now(timezone.utc)
        task = {
            "status": "in_progress",
            "started_at": now.isoformat(),
            "a2a_lease_expires_at": (now + timedelta(seconds=30)).isoformat(),
        }
        self.assertEqual(a2a_controller._execution_lease_state(task, 30, now=now), "active")

    def test_expired_a2a_lease_is_terminal_candidate(self) -> None:
        now = datetime.now(timezone.utc)
        task = {
            "status": "in_progress",
            "started_at": (now - timedelta(minutes=10)).isoformat(),
            "a2a_lease_expires_at": (now - timedelta(seconds=1)).isoformat(),
        }
        self.assertEqual(a2a_controller._execution_lease_state(task, 30, now=now), "expired")

    def test_legacy_in_progress_without_lease_expires_from_started_at(self) -> None:
        now = datetime.now(timezone.utc)
        task = {
            "status": "in_progress",
            "started_at": (now - timedelta(minutes=5)).isoformat(),
        }
        self.assertEqual(a2a_controller._execution_lease_state(task, 30, now=now), "expired")


if __name__ == "__main__":
    unittest.main()
