from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import a2a_controller, gpu_inference_lease


class A2aGpuBackpressureTests(unittest.TestCase):
    def test_controller_queues_when_gpu_lease_unavailable(self):
        task = {
            "task_id": "ops_a2a_gpu",
            "status": "proposed",
            "title": "[A2A:AG-42] repair service",
            "checklist": ["Run bounded repair"],
            "created_at": "2026-08-28T00:00:00+00:00",
        }
        fake_db = mock.MagicMock()
        fake_db.__getitem__.return_value.find.return_value.sort.return_value.limit.return_value = [task]
        fake_db.__getitem__.return_value.find_one.return_value = task
        with mock.patch.object(a2a_controller, "mongo_store") as mongo_store, mock.patch.object(
            gpu_inference_lease,
            "acquire_gpu_inference_lease",
            return_value={"ok": False, "error": "gpu_capacity_zero", "queued": True},
        ), mock.patch.object(a2a_controller.coordination_live, "update_ops_task_state") as update_state:
            mongo_store.get_db.return_value = fake_db
            result = a2a_controller.controller_tick(limit=1, dry_run=False, db=fake_db)

        self.assertTrue(result["executed"])
        self.assertEqual(result["executed"][0]["status"], "queued_gpu")
        update_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
