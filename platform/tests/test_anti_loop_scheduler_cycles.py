from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import dev_swarm_scheduler


class SchedulerAntiLoopCycleTests(unittest.TestCase):
    def test_reconcile_does_not_reset_terminal_retry_budget(self):
        fake_db = mock.MagicMock()
        fake_db.__getitem__.return_value.count_documents.return_value = 0
        fake_db.__getitem__.return_value.update_many.return_value = mock.MagicMock(modified_count=0)
        fake_db.__getitem__.return_value.find.return_value = []
        with mock.patch.object(dev_swarm_scheduler, "_db", return_value=fake_db), mock.patch.object(
            dev_swarm_scheduler,
            "_reclaim_stale_workers",
            return_value={"retriable": 0, "exhausted": 0},
        ), mock.patch.object(dev_swarm_scheduler, "capacity_governor_vnext") as governor:
            governor.enrich_capacity_snapshot.side_effect = lambda snap, **kwargs: snap
            result = dev_swarm_scheduler.reconcile_capacity_state(reason="anti_loop_test")
        self.assertTrue(result["ok"])
        self.assertEqual(result["stale_workers_retryable"], 0)


if __name__ == "__main__":
    unittest.main()
