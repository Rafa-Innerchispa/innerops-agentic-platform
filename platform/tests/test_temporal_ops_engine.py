import asyncio
from datetime import datetime, timezone
import unittest

from inneros_core_runtime.temporal_activities import (
    TaskEnvelopeV1,
    ProtocolMutationGuard,
    _build_langgraph_agent,
    LANGGRAPH_AVAILABLE,
    activity_validate_envelope,
    activity_hydrate_worktree,
    activity_execute_agent_graph,
    activity_sync_mongo_mirror,
)
from inneros_core_runtime.temporal_workflows import OpsTaskWorkflow


class TestTemporalOpsEngine(unittest.IsolatedAsyncioTestCase):
    def test_task_envelope_serialization(self):
        env = TaskEnvelopeV1(
            task_id="ops_test_123",
            title="Test Task",
            assignee="antigravity",
            objective="Implement feature",
        )
        d = env.to_dict()
        self.assertEqual(d["task_id"], "ops_test_123")
        self.assertEqual(d["assignee"], "antigravity")

        reconstructed = TaskEnvelopeV1.from_dict(d)
        self.assertEqual(reconstructed.task_id, "ops_test_123")
        self.assertEqual(reconstructed.assignee, "antigravity")

    def test_mutation_guard_allows_valid_assignee(self):
        env = TaskEnvelopeV1(task_id="ops_1", assignee="antigravity", revision=2, status="in_progress")
        res = ProtocolMutationGuard.validate_mutation(
            envelope=env,
            caller_agent="antigravity",
            acknowledged_revision=2,
        )
        self.assertTrue(res["allowed"])
        self.assertEqual(res["reason"], "ALLOWED")

    def test_mutation_guard_blocks_unassigned_agent(self):
        env = TaskEnvelopeV1(task_id="ops_1", assignee="chatgpt", revision=1, status="in_progress")
        res = ProtocolMutationGuard.validate_mutation(
            envelope=env,
            caller_agent="antigravity",
            acknowledged_revision=1,
        )
        self.assertFalse(res["allowed"])
        self.assertEqual(res["reason"], "TASK_NOT_ASSIGNED")
        self.assertIn("assigned to 'chatgpt'", res["message"])

    def test_mutation_guard_blocks_terminal_task_mutation(self):
        for terminal_status in ["completed", "cancelled", "superseded"]:
            env = TaskEnvelopeV1(task_id="ops_1", assignee="antigravity", revision=1, status=terminal_status)
            res = ProtocolMutationGuard.validate_mutation(
                envelope=env,
                caller_agent="antigravity",
                acknowledged_revision=1,
            )
            self.assertFalse(res["allowed"])
            self.assertEqual(res["reason"], "TASK_TERMINAL")

    def test_mutation_guard_blocks_stale_revision(self):
        env = TaskEnvelopeV1(task_id="ops_1", assignee="antigravity", revision=3, status="in_progress")
        res = ProtocolMutationGuard.validate_mutation(
            envelope=env,
            caller_agent="antigravity",
            acknowledged_revision=2,  # Stale ACK!
        )
        self.assertFalse(res["allowed"])
        self.assertEqual(res["reason"], "STALE_TASK_REVISION")

    def test_langgraph_agent_graph_compiles(self):
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("LangGraph not installed")
        graph = _build_langgraph_agent()
        self.assertIsNotNone(graph)

    async def test_validate_envelope_activity(self):
        env = TaskEnvelopeV1(task_id="ops_test_val", assignee="antigravity", revision=1)
        res = await activity_validate_envelope(env.to_dict())
        self.assertTrue(res["ok"])
        self.assertEqual(res["task_id"], "ops_test_val")


if __name__ == "__main__":
    unittest.main()
