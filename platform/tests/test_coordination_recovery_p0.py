"""Offline P0 canaries for the coordination recovery branch.

These tests intentionally avoid live Mongo, NATS, Temporal, and model services.
They validate the contracts that must be true before a runtime canary deploy.
"""
from __future__ import annotations

import inspect
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from inneros_core_runtime import coordination_ingest
from inneros_core_runtime import coordination_live
from inneros_core_runtime import durable_coordination_spine as spine
from inneros_core_runtime import mcp_diagnostics
from inneros_core_runtime import agent_identity
from inneros_core_runtime.memory import agent_messages


ROOT = Path(__file__).resolve().parents[1]


class CoordinationRecoveryP0Tests(unittest.TestCase):
    def test_temporal_worker_registers_every_workflow_activity(self):
        source = (ROOT / "inneros_core_runtime" / "temporal_worker.py").read_text()
        self.assertIn("activity_publish_nats_event,", source)
        self.assertIn("activity_validate_completion_gate,", source)
        activities_block = source.split("activities=[", 1)[1].split("]", 1)[0]
        self.assertIn("activity_publish_nats_event", activities_block)
        self.assertIn("activity_validate_completion_gate", activities_block)

    def test_local_candidate_does_not_fabricate_execution_evidence(self):
        source = (ROOT / "inneros_core_runtime" / "temporal_activities.py").read_text()
        self.assertNotIn('code_diff": "+ implemented logic"', source)
        self.assertIn('"candidate_only": True', source)
        self.assertIn('"requires_bounded_executor": True', source)

    def test_task_admission_uses_temporal_and_is_idempotent(self):
        captured: list[dict] = []

        def fake_start(task: dict) -> dict:
            captured.append(task)
            return {
                "ok": True,
                "workflow_id": task["workflow_id"],
                "run_id": "run-test",
            }

        with (
            patch.object(spine, "start_task_workflow", side_effect=fake_start),
            patch.object(coordination_live, "_publish_task_event", return_value={"ok": True}),
            patch.object(coordination_live, "bump_revision", return_value={"ok": True}),
        ):
            first = coordination_live.create_ops_task(
                "qwen-coding",
                "P0 offline canary",
                idempotency_key="p0-offline-canary",
            )
            second = coordination_live.create_ops_task(
                "qwen-coding",
                "P0 offline canary",
                idempotency_key="p0-offline-canary",
            )

        self.assertTrue(first["ok"])
        self.assertEqual(first["authority"], "temporal")
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(captured[0]["workflow_id"], f"ops_task:{first['task_id']}")

    def test_task_admission_preserves_source_message_id(self):
        captured: list[dict] = []

        def fake_start(task: dict) -> dict:
            captured.append(task)
            return {
                "ok": True,
                "workflow_id": task["workflow_id"],
                "run_id": "run-source-message",
            }

        with (
            patch.object(spine, "start_task_workflow", side_effect=fake_start),
            patch.object(coordination_live, "_publish_task_event", return_value={"ok": True}),
            patch.object(coordination_live, "bump_revision", return_value={"ok": True}),
        ):
            result = coordination_live.create_ops_task(
                "qwen-coding",
                "Normalized task message",
                idempotency_key="message:msg_test_source",
                source_message_id="msg_test_source",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["task"]["source_message_id"], "msg_test_source")
        self.assertEqual(captured[0]["source_message_id"], "msg_test_source")

    def test_task_message_full_flow_reaches_temporal_with_source_linkage(self):
        captured: list[dict] = []
        message_id = "msg_full_flow"
        collection = MagicMock()

        def fake_start(task: dict) -> dict:
            captured.append(task)
            return {
                "ok": True,
                "workflow_id": task["workflow_id"],
                "run_id": "run-full-flow",
            }

        with (
            patch(
                "raphiia_openai.memory.agent_messages.create_agent_message",
                return_value={
                    "ok": True,
                    "created": True,
                    "message_id": message_id,
                    "correlation_id": "corr-full-flow",
                },
            ),
            patch.object(
                coordination_ingest.mongo_store,
                "get_db",
                return_value={coordination_ingest.COL_AGENT_MESSAGES: collection},
            ),
            patch.object(spine, "start_task_workflow", side_effect=fake_start),
            patch.object(coordination_ingest.coordination_live, "_publish_task_event", return_value={"ok": True}),
            patch.object(coordination_ingest.coordination_live, "bump_revision", return_value={"ok": True}),
        ):
            result = coordination_ingest.ingest_agent_message(
                from_agent="CHATGPT",
                target_agent="qwen-coding",
                title="[P0] Full message task flow",
                body=(
                    "repo: Rafa-Innerchispa/innerops-agentic-platform\n"
                    "related_project: coordination-recovery\n"
                    "conversation_ref: session-regression\n"
                    "- Preserve source linkage\n"
                    "- Admit only through Temporal"
                ),
                message_type="task",
                idempotency_key="message:msg_full_flow",
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["normalization"]["ok"])
        self.assertEqual(len(captured), 1)
        admitted = captured[0]
        self.assertEqual(admitted["source_message_id"], message_id)
        self.assertEqual(admitted["conversation_ref"], "session-regression")
        self.assertEqual(admitted["related_project"], "coordination-recovery")
        self.assertEqual(admitted["repo"], "Rafa-Innerchispa/innerops-agentic-platform")
        self.assertEqual(result["normalization"]["authority"], "temporal")
        collection.update_one.assert_called_once()

    def test_revision_bump_uses_current_coordination_state_api(self):
        with (
            patch.object(
                coordination_live.mongo_store,
                "get_coordination_state",
                return_value={"ok": False, "key": coordination_live.STATE_KEY},
            ),
            patch.object(
                coordination_live.mongo_store,
                "upsert_coordination_state",
                return_value={"ok": True},
            ) as upsert,
        ):
            result = coordination_live.bump_revision(
                reason="offline compatibility canary",
                source="test",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["revision"], 1)
        upsert.assert_called_once()
        self.assertEqual(upsert.call_args.kwargs["key"], coordination_live.STATE_KEY)
        self.assertEqual(upsert.call_args.kwargs["data"]["revision"], 1)

    def test_direct_completion_is_fail_closed(self):
        result = coordination_live.complete_ops_task(
            "ops_test",
            evidence={"test_exit_code": 0},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "direct_completion_forbidden")
        self.assertEqual(result["authority"], "temporal")

    def test_arbitrary_direct_state_mutation_is_rejected(self):
        result = coordination_live.update_ops_task_state(
            "ops_test",
            "completed",
            actor="test",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "temporal_owns_task_lifecycle")

    def test_message_persistence_failure_is_visible(self):
        with patch.object(spine, "MongoClient", side_effect=RuntimeError("db unavailable")):
            result = spine.create_durable_message(
                task_id="ops_test",
                workflow_id="ops_task:ops_test",
                sender="qwen-coding",
                recipient="chatgpt",
                subject="P0 canary",
                content="Must not disappear silently",
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["persisted"])
        self.assertIn("message_persistence_failed", result["error"])

    def test_message_query_failure_is_not_reported_as_empty_inbox(self):
        with (
            patch.object(spine, "MongoClient", side_effect=RuntimeError("db unavailable")),
            self.assertRaisesRegex(RuntimeError, "message_query_failed"),
        ):
            spine.query_durable_messages(recipient="chatgpt")

    def test_inbox_does_not_ack_by_default(self):
        default = inspect.signature(agent_messages.poll_agent_inbox).parameters["auto_ack"].default
        self.assertIs(default, False)

    def test_mcp_diagnostics_accepts_profile_projection(self):
        signature = inspect.signature(mcp_diagnostics.diagnose_mcp_session)
        self.assertIn("profile", signature.parameters)
        source = inspect.getsource(mcp_diagnostics.diagnose_mcp_session)
        self.assertIn("expected_tool_count = len(expected_tools)", source)

    def test_local_agent_mailboxes_do_not_fall_back_to_chatgpt(self):
        self.assertEqual(agent_identity.canonical_mailbox("qwen-coding"), "qwen_coding")
        self.assertEqual(agent_identity.canonical_mailbox("codex-repair"), "codex_repair")
        self.assertEqual(
            agent_identity.canonical_mailbox("integration-guardian"),
            "integration_guardian",
        )


if __name__ == "__main__":
    unittest.main()