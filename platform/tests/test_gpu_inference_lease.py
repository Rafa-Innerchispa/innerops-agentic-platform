from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import gpu_inference_lease


class GpuInferenceLeaseTests(unittest.TestCase):
    def test_acquire_denied_when_capacity_zero(self):
        with mock.patch.object(
            gpu_inference_lease,
            "_capacity_budget",
            return_value={"ok": False, "admittable_now": 0, "capacity": {}},
        ):
            result = gpu_inference_lease.acquire_gpu_inference_lease(agent="dev_swarm", task_id="ops_test")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "gpu_capacity_zero")
        self.assertTrue(result["queued"])

    def test_acquire_returns_resource_lease_id(self):
        with mock.patch.object(
            gpu_inference_lease,
            "_capacity_budget",
            return_value={"ok": True, "admittable_now": 1, "capacity": {}},
        ), mock.patch.object(
            gpu_inference_lease,
            "_node_id",
            return_value="ralfiia-amd",
        ), mock.patch.object(
            gpu_inference_lease.racb_locks,
            "manage_coordination_lock",
            return_value={"ok": True, "action": "acquire"},
        ):
            result = gpu_inference_lease.acquire_gpu_inference_lease(agent="dev_swarm", task_id="ops_test")
        self.assertTrue(result["ok"])
        self.assertEqual(result["resource_lease_id"], "gpu:inference:ralfiia-amd:generation:0")

    def test_release_is_idempotent_without_resource(self):
        result = gpu_inference_lease.release_gpu_inference_lease(agent="dev_swarm", task_id="ops_test", resource_lease_id="")
        self.assertTrue(result["ok"])
        self.assertFalse(result["released"])


if __name__ == "__main__":
    unittest.main()
