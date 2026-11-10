"""Contrato de productores legacy: queued/qwen-coding/internal -> dev_swarm.

Los productores viejos crean tareas con etiquetas que el despachador no
acepta. normalize_producer_task las mapea al contrato canonico antes de
evaluar elegibilidad, sin mutar el dict original ni Mongo.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

from inneros_core_runtime import dev_swarm_scheduler as scheduler


LEGACY_TASK = {
    "task_id": "ops_legacy_producer_probe",
    "title": "innerops agentic platform repair scheduler tick",
    "status": "queued",
    "assignee": "qwen-coding",
    "execution_lane": "internal",
    "repo": "Rafa-Innerchispa/innerops-agentic-platform",
    "task_class": "coding",
}


class NormalizeProducerTaskTests(unittest.TestCase):
    def test_maps_legacy_labels(self):
        out = scheduler.normalize_producer_task(dict(LEGACY_TASK))
        self.assertEqual(out["status"], "proposed")
        self.assertEqual(out["assignee"], "dev_swarm")
        self.assertEqual(out["execution_lane"], scheduler.LOCAL_DEV_SWARM_LANE)

    def test_does_not_mutate_input(self):
        task = dict(LEGACY_TASK)
        scheduler.normalize_producer_task(task)
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["assignee"], "qwen-coding")
        self.assertEqual(task["execution_lane"], "internal")

    def test_leaves_canonical_task_untouched(self):
        task = {
            "status": "proposed",
            "assignee": "dev_swarm",
            "execution_lane": scheduler.LOCAL_DEV_SWARM_LANE,
        }
        self.assertEqual(scheduler.normalize_producer_task(task), task)

    def test_normalizes_nested_payload_lane(self):
        task = {"payload": {"execution_lane": "internal"}}
        out = scheduler.normalize_producer_task(task)
        self.assertEqual(out["payload"]["execution_lane"], scheduler.LOCAL_DEV_SWARM_LANE)
        self.assertEqual(task["payload"]["execution_lane"], "internal")

    def test_legacy_mirror_defines_same_contract(self):
        legacy = Path(__file__).resolve().parent.parent.parent / "raphiia_openai" / "dev_swarm_scheduler.py"
        if not legacy.is_file():
            legacy = (
                Path(__file__).resolve().parent.parent
                / "raphiia_openai"
                / "dev_swarm_scheduler.py"
            )
        source = legacy.read_text(encoding="utf-8")
        self.assertIn("def normalize_producer_task(", source)
        self.assertIn('"queued": "proposed"', source)
        self.assertIn('"qwen-coding": "dev_swarm"', source)
        self.assertIn('"internal": LOCAL_DEV_SWARM_LANE', source)

    def test_eligible_reason_accepts_legacy_shaped_task(self):
        with (
            patch.object(
                scheduler.local_execution_plane,
                "repo_policy_status",
                return_value={"ok": True},
            ),
            patch.object(
                scheduler.dev_swarm_dispatch_reconcile,
                "is_dev_swarm_managed_task",
                return_value=False,
            ),
        ):
            ok, reason, repo = scheduler._eligible_reason(dict(LEGACY_TASK))
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, "Rafa-Innerchispa/innerops-agentic-platform")


if __name__ == "__main__":
    unittest.main()
