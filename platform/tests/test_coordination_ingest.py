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
    def test_heartbeat_rejects_wrong_owner(self) -> None:
        collection = MagicMock()
        collection.find_one.return_value = {"task_id": "ops_1", "status": "in_progress", "owner": "gemini"}
        with patch("raphiia_openai.mongo_store.get_db", return_value={"ralfia_ops_tasks": collection}):
            result = coordination_live.heartbeat_ops_task("ops_1", "codex")
        self.assertEqual(result["error"], "ownership_conflict")
        collection.update_one.assert_not_called()

    def test_heartbeat_updates_active_task(self) -> None:
        collection = MagicMock()
        collection.find_one.return_value = {"task_id": "ops_1", "status": "in_progress", "owner": "codex"}
        collection.update_one.return_value = SimpleNamespace(modified_count=1)
        with patch("raphiia_openai.mongo_store.get_db", return_value={"ralfia_ops_tasks": collection}):
            result = coordination_live.heartbeat_ops_task("ops_1", "codex", next_action="verify")
        self.assertTrue(result["ok"])
        self.assertEqual(result["owner"], "codex")


if __name__ == "__main__":
    unittest.main()
