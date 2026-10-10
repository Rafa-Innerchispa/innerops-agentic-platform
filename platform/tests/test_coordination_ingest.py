from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from raphiia_openai import coordination_ingest, coordination_live, racb_protocol


class CoordinationIngestTests(unittest.TestCase):
    def test_p0_message_creates_linked_task(self) -> None:
        message_result = {
            "ok": True,
            "created": True,
            "message_id": "msg_source",
            "correlation_id": "corr-123",
        }
        task_result = {"ok": True, "created": True, "task_id": "ops_123", "correlation_id": "corr-123"}
        collection = MagicMock()
        db = {"ralfia_agent_messages": collection}
        with (
            patch("raphiia_openai.memory.agent_messages.create_agent_message", return_value=message_result) as create_message,
            patch("raphiia_openai.coordination_live.create_ops_task", return_value=task_result) as create_task,
            patch("raphiia_openai.mongo_store.get_db", return_value=db),
        ):
            result = coordination_ingest.ingest_agent_message(
                from_agent="CHATGPT",
                target_agent="codex",
                title="[P0] Probar coordinación",
                body="correlation_id: corr-123\nproject: coordination\nconversation_ref: session-9\n- Ejecutar E2E\n- Guardar evidencia",
                priority="critical",
            )

        self.assertEqual(result["normalization"]["task_id"], "ops_123")
        create_message.assert_called_once()
        kwargs = create_task.call_args.kwargs
        self.assertEqual(kwargs["correlation_id"], "corr-123")
        self.assertEqual(kwargs["source_message_id"], "msg_source")
        self.assertEqual(kwargs["conversation_ref"], "session-9")
        self.assertEqual(kwargs["related_project"], "coordination")
        self.assertEqual(kwargs["checklist"], ["Ejecutar E2E", "Guardar evidencia"])
        collection.update_one.assert_called_once()

    def test_normal_message_does_not_create_task(self) -> None:
        with (
            patch("raphiia_openai.memory.agent_messages.create_agent_message", return_value={"ok": True, "message_id": "msg_1"}),
            patch("raphiia_openai.coordination_live.create_ops_task") as create_task,
        ):
            result = coordination_ingest.ingest_agent_message(
                from_agent="CHATGPT",
                target_agent="codex",
                title="Nota informativa",
                body="Solo contexto; no es una orden.",
            )
        self.assertTrue(result["ok"])
        create_task.assert_not_called()

    def test_distinguishes_chatgpt_accounts_without_breaking_mailbox(self) -> None:
        message_result = {
            "ok": True,
            "created": True,
            "message_id": "msg_source",
            "correlation_id": "corr-identity",
        }
        task_result = {"ok": True, "created": True, "task_id": "ops_identity", "correlation_id": "corr-identity"}
        collection = MagicMock()
        db = {"ralfia_agent_messages": collection}
        payload = {"actor_account": "PCDoctorGI", "actor_host": "chatgpt-enterprise", "actor_lane": "A"}
        with (
            patch("raphiia_openai.memory.agent_messages.create_agent_message", return_value=message_result) as create_message,
            patch("raphiia_openai.coordination_live.create_ops_task", return_value=task_result) as create_task,
            patch("raphiia_openai.mongo_store.get_db", return_value=db),
        ):
            result = coordination_ingest.ingest_agent_message(
                from_agent="CHATGPT_A",
                target_agent="codex",
                title="[P0] Identidad",
                body="correlation_id: corr-identity\n- probar identidad",
                priority="critical",
                payload=payload,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(create_message.call_args.kwargs["from_agent"], "chatgpt_a")
        kwargs = create_task.call_args.kwargs
        self.assertEqual(kwargs["from_agent"], "chatgpt_a_pcdoctorgi_chatgpt-enterprise_a")
        patch_doc = collection.update_one.call_args.args[1]["$set"]
        self.assertEqual(patch_doc["from_identity"]["mailbox"], "chatgpt_a")
        self.assertEqual(patch_doc["from_identity"]["account"], "pcdoctorgi")

    def test_in_progress_sets_first_heartbeat(self) -> None:
        transition = racb_protocol.build_transition(
            current_status="accepted",
            target_status="in_progress",
            actor="codex",
            current_revision=2,
            owner="codex",
        )
        self.assertTrue(transition["ok"])
        self.assertIn("last_heartbeat_at", transition["patch"])


class HeartbeatTests(unittest.TestCase):
    def test_heartbeat_signals_temporal(self) -> None:
        with patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True, "task_id": "ops_1", "signal": "heartbeat"},
        ) as signal:
            result = coordination_live.heartbeat_ops_task(
                "ops_1",
                "codex",
                phase="verification",
                next_action="verify",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["authority"], "temporal")
        signal.assert_called_once()
        args = signal.call_args.args
        self.assertEqual(args[0], "ops_1")
        self.assertEqual(args[1], "heartbeat")
        self.assertEqual(args[2]["actor"], "codex")
        self.assertEqual(args[2]["phase"], "verification")
        self.assertEqual(args[2]["next_action"], "verify")


class TerminalEvidenceGateTests(unittest.TestCase):
    def test_direct_completion_is_temporal_owned(self) -> None:
        result = coordination_live.update_ops_task_state(
            "ops_repo",
            "completed",
            actor="codex",
            evidence={"remote_commit_sha": "a" * 40},
            force_handoff=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "temporal_owns_task_lifecycle")
        self.assertEqual(result["authority"], "temporal")

    def test_complete_ops_task_is_fail_closed(self) -> None:
        result = coordination_live.complete_ops_task(
            "ops_repo",
            actor="codex",
            evidence={"remote_commit_sha": "a" * 40},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "direct_completion_forbidden")
        self.assertEqual(result["authority"], "temporal")


if __name__ == "__main__":
    unittest.main()


def test_do_not_auto_dispatch_still_materializes_ops_task():
    from unittest.mock import patch
    from inneros_core_runtime import coordination_ingest as ci

    fake_message = {
        "ok": True,
        "message_id": "msg_cursor_wait",
        "correlation_id": "cursor-wait-test",
    }
    fake_task = {
        "ok": True,
        "task_id": "ops_cursor_wait",
        "workflow_id": "ops_task:ops_cursor_wait",
        "status": "awaiting_cursor_claim",
    }

    with (
        patch("raphiia_openai.memory.agent_messages.create_agent_message", return_value=fake_message),
        patch.object(ci.coordination_live, "create_ops_task", return_value=fake_task) as create_task,
        patch.object(ci.mongo_store, "get_db"),
    ):
        out = ci.ingest_agent_message(
            from_agent="CHATGPT",
            target_agent="cursor",
            title="P0 owner interactive task",
            body="Execute bounded task.",
            priority="p0",
            correlation_id="cursor-wait-test",
            message_type="task",
            payload={
                "repo": "Rafa-Innerchispa/innerops-agentic-platform",
                "execution_lane": "cursor_interactive",
                "preferred_provider": "cursor",
                "do_not_auto_dispatch": True,
            },
            idempotency_key="cursor-wait-test",
        )

    assert create_task.called
    kwargs = create_task.call_args.kwargs
    assert kwargs["do_not_auto_dispatch"] is True
    assert out["normalization"]["task_id"] == "ops_cursor_wait"
    assert out["normalization"]["workflow_id"] == "ops_task:ops_cursor_wait"