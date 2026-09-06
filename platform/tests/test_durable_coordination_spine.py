from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime import a2a_bridge, durable_coordination_spine as spine


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
        self.assertIn("inneros.task.heartbeat", event["subject"])
        self.assertEqual(event["envelope"]["live_mode"], "LIVE")

    def test_rejects_unknown_event_type(self):
        with self.assertRaises(ValueError):
            spine.build_event("task.random", actor="codex")

    def test_memory_sink_supports_dry_run_without_mongo(self):
        events: list[dict] = []
        sink = spine.MemoryEventSink(events)

        result = spine.publish_event(
            "scheduler.selected",
            actor="dev_swarm",
            task_id="ops_abc",
            correlation_id="corr-2",
            sink=sink,
            live_mode="NON-LIVE",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "memory")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["live_mode"], "NON-LIVE")

    def test_temporal_workflow_intent_is_explicitly_not_live_adapter(self):
        intent = spine.workflow_intent_for_task(
            {"task_id": "ops_abc", "correlation_id": "corr-3", "repo": "Rafa-Innerchispa/innerops-agentic-platform"}
        )

        self.assertTrue(intent["ok"])
        self.assertEqual(intent["backend"], "temporal")
        self.assertFalse(intent["ready"])
        self.assertEqual(intent["workflow_id"], "inneros-task-ops_abc")
        self.assertIn("unsafe_operation", intent["retry_policy"]["non_retryable_errors"])

    @patch("inneros_core_runtime.a2a_bridge.durable_coordination_spine.publish_event")
    def test_a2a_dispatch_publishes_durable_event(self, publish_event):
        publish_event.return_value = {"ok": True, "event_id": "evt_1", "event": {}}
        ops = Mock()
        store = Mock()
        ops.create_task.return_value = {"ok": True, "task_id": "ops_1", "created": True}
        bridge = a2a_bridge.A2ABridge(ops=ops, store=store)

        result = bridge.dispatch(agent_id="qwen-coding", title="T", body="B", dry_run=False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["event_id"], "evt_1")
        publish_event.assert_called_once()
        self.assertEqual(publish_event.call_args.args[0], "a2a.dispatched")

    @patch("inneros_core_runtime.a2a_bridge.durable_coordination_spine.publish_event")
    def test_a2a_status_projection_publishes_event_and_refuses_evidence_free_completion(self, publish_event):
        publish_event.return_value = {"ok": True, "event_id": "evt_2", "event": {}}
        ops = Mock()
        store = Mock()
        store.get.return_value = {
            "a2a_task_id": "a2a_1",
            "context_id": "ctx",
            "correlation_id": "corr",
            "agent_id": "AG-25",
            "ops_task_id": "ops_1",
            "traceparent": "",
            "envelope": {},
        }
        ops.get_task.return_value = {"task_id": "ops_1", "status": "completed", "evidence": {}}
        bridge = a2a_bridge.A2ABridge(ops=ops, store=store)

        result = bridge.task_status("a2a_1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"]["state"], "working")
        self.assertEqual(result["integrity_error"], "terminal_ops_task_missing_evidence")
        self.assertEqual(result["event_id"], "evt_2")
        publish_event.assert_called_once()
        self.assertEqual(publish_event.call_args.args[0], "a2a.status_projected")

    def test_nats_sink_fails_closed_when_package_missing(self):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "nats":
                raise ImportError("missing nats")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            result = spine.NatsJetStreamSink().publish(
                spine.build_event("task.heartbeat", actor="codex", task_id="ops_no_net")
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["backend"], "nats_jetstream")
        self.assertIn(result["reason"], {"nats_py_not_installed", "async_event_loop_already_running"})

    @patch.dict("os.environ", {"INNEROS_NATS_ENABLED": "1"})
    def test_default_sink_dual_writes_when_nats_enabled(self):
        sink = spine.default_sink()

        self.assertIsInstance(sink, spine.CompositeEventSink)
        self.assertEqual(type(sink.sinks[0]).__name__, "MongoEventSink")
        self.assertEqual(type(sink.sinks[1]).__name__, "NatsJetStreamSink")

    @patch.dict("os.environ", {"INNEROS_OTEL_ENABLED": "0"})
    def test_otel_disabled_is_explicit_noop(self):
        event = spine.build_event("task.heartbeat", actor="codex", task_id="ops_otel")

        result = spine.emit_otel_event(event)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "otel_disabled")

    @patch("inneros_core_runtime.durable_coordination_spine.importlib.util.find_spec", return_value=None)
    def test_temporal_status_fails_closed_when_sdk_missing(self, _find_spec):
        result = spine.temporal_connection_status(address="127.0.0.1:7233")

        self.assertFalse(result["ok"])
        self.assertEqual(result["backend"], "temporal")
        self.assertEqual(result["reason"], "temporalio_not_installed")

    @patch.dict("os.environ", {"INNEROS_TEMPORAL_ADDRESS": "127.0.0.1:7233"})
    @patch("inneros_core_runtime.durable_coordination_spine.importlib.util.find_spec", return_value=object())
    def test_temporal_status_uses_env_address(self, _find_spec):
        async def fake_connect(address: str, namespace: str, timeout_sec: float):
            return {"ok": True, "backend": "temporal", "ready": True, "address": address, "namespace": namespace}

        with patch("inneros_core_runtime.durable_coordination_spine._temporal_connect_async", side_effect=fake_connect) as connect:
            result = spine.temporal_connection_status()

        self.assertTrue(result["ok"])
        self.assertEqual(result["address"], "127.0.0.1:7233")
        connect.assert_called_once_with("127.0.0.1:7233", "default", 2.0)


if __name__ == "__main__":
    unittest.main()
