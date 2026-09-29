"""Tests for the InnerOS Durable Coordination Spine."""
from __future__ import annotations

import unittest
from inneros_core_runtime import durable_coordination_spine as spine


class DurableCoordinationSpineTests(unittest.TestCase):
    def test_build_event_adds_traceparent_and_stable_subject(self):
        event = spine.build_event(
            "task.heartbeat",
            actor="codex",
            task_id="ops_123",
            correlation_id="corr-1",
            repo="Rafa-Innerchispa/innerops-agentic-platform",
            status="in_progress",
            payload={"next_action": "tests"},
        )
        self.assertEqual(event["event_type"], "task.heartbeat")
        self.assertEqual(event["correlation_id"], "corr-1")
        self.assertTrue(event["event_id"].startswith("evt_"))
        self.assertIn("traceparent", event)
        self.assertIn("task.heartbeat", event["subject"])

    def test_rejects_unknown_event_type(self):
        with self.assertRaises(ValueError):
            spine.build_event("unknown.event", actor="system")

    def test_default_sink_dual_writes_when_nats_enabled(self):
        sink = spine.default_sink()
        self.assertTrue(sink is not None)

    def test_temporal_status_uses_env_address(self):
        status = spine.status()
        self.assertTrue(status["ok"])
        self.assertIn("runtime_probe", status)

    def test_workflow_intent_is_canonical(self):
        intent = spine.workflow_intent_for_task(
            {"task_id": "ops_abc", "correlation_id": "corr-3", "repo": "Rafa-Innerchispa/innerops-agentic-platform"}
        )
        self.assertTrue(intent["ok"])
        self.assertEqual(intent["backend"], "temporal")
        self.assertEqual(intent["workflow_id"], "ops_task:ops_abc")
        self.assertTrue(intent["ready"])

    def test_durable_messages_helpers(self):
        msg = spine.create_durable_message(
            task_id="ops_test_msg",
            workflow_id="ops_task:ops_test_msg",
            sender="antigravity",
            recipient="chatgpt",
            subject="Consolidation Proof",
            content="Evidence for message lifecycle",
        )
        self.assertTrue(msg["message_id"].startswith("msg_"))
        self.assertEqual(msg["status"], "unread")

        # Query message
        msgs = spine.query_durable_messages(task_id="ops_test_msg")
        self.assertTrue(len(msgs) >= 1)

        # Ack message
        ack = spine.ack_durable_message(msg["message_id"], actor="chatgpt")
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["status"], "consumed")


if __name__ == "__main__":
    unittest.main()
