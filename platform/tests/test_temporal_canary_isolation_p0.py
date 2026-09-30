from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from inneros_core_runtime import durable_coordination_spine


class TemporalCanaryIsolationP0Tests(unittest.TestCase):
    def test_workflow_queue_uses_environment_override(self) -> None:
        with patch.dict(
            os.environ,
            {"INNEROS_TEMPORAL_TASK_QUEUE": "inneros-p0-canary"},
        ):
            intent = durable_coordination_spine.workflow_intent_for_task(
                {
                    "task_id": "p0_canary_test",
                    "correlation_id": "p0_canary_test",
                }
            )

        self.assertEqual(intent["task_queue"], "inneros-p0-canary")

    def test_mongo_database_uses_environment_override(self) -> None:
        with patch.dict(
            os.environ,
            {"INNEROS_MONGO_DB": "pcdoctor_swarm_canary"},
        ):
            self.assertEqual(
                durable_coordination_spine._mongo_db_name(),
                "pcdoctor_swarm_canary",
            )

    def test_mongo_event_sink_has_no_fixed_database(self) -> None:
        sink = durable_coordination_spine.MongoEventSink()
        self.assertEqual(sink.db_name, "")

    def test_temporal_activities_expose_isolation_controls(self) -> None:
        source = Path(
            "platform/inneros_core_runtime/temporal_activities.py"
        ).read_text(encoding="utf-8")

        self.assertIn("INNEROS_MONGO_DB", source)
        self.assertIn("INNEROS_WORKTREE_BASE", source)
        self.assertNotIn('client["pcdoctor_swarm"]', source)
        self.assertNotIn(
            'Path("/home/rlopez/inneros/inneros_core/worktrees")',
            source,
        )

    def test_success_fixture_is_restricted_to_isolated_canary(self) -> None:
        source = Path(
            "platform/inneros_core_runtime/temporal_activities.py"
        ).read_text(encoding="utf-8")

        self.assertIn('canary_test_type") == "successful_diff"', source)
        self.assertIn('envelope.execution_lane != "canary"', source)
        self.assertIn('MONGODB_DB != "pcdoctor_swarm_canary"', source)
        self.assertIn('"/.canary/worktrees" not in worktree', source)
        self.assertIn("CANARY_ISOLATION_VIOLATION", source)
        self.assertIn("p0-success-evidence.txt", source)

    def test_durable_spine_has_no_direct_production_db_index(self) -> None:
        source = Path(
            "platform/inneros_core_runtime/durable_coordination_spine.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn('client["pcdoctor_swarm"]', source)
        self.assertIn("INNEROS_TEMPORAL_TASK_QUEUE", source)


if __name__ == "__main__":
    unittest.main()
