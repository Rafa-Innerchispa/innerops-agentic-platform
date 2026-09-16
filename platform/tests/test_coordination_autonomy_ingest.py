from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Force this isolated worktree's platform package ahead of the live runtime copy.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from raphiia_openai import coordination_ingest
from inneros_core_runtime import agent_autonomy_policy as policy


class CoordinationAutonomyIngestTests(unittest.TestCase):
    def test_p0_codex_task_gets_autonomy_policy_and_execution_policy(self):
        message_result = {"ok": True, "created": True, "message_id": "msg_auto", "correlation_id": "corr-auto"}
        task_result = {"ok": True, "created": True, "task_id": "ops_auto", "correlation_id": "corr-auto"}
        collection = MagicMock()
        with (
            patch("raphiia_openai.memory.agent_messages.create_agent_message", return_value=message_result) as create_message,
            patch("raphiia_openai.coordination_live.create_ops_task", return_value=task_result) as create_task,
            patch("raphiia_openai.mongo_store.get_db", return_value={"ralfia_agent_messages": collection}),
        ):
            result = coordination_ingest.ingest_agent_message(
                from_agent="CHATGPT",
                target_agent="codex",
                title="[P0] Finish autonomously",
                body="correlation_id: corr-auto\n- Run tests\n- Fix failures",
                priority="p0",
            )

        self.assertTrue(result["ok"])
        msg_kwargs = create_message.call_args.kwargs
        self.assertIn(policy.POLICY_MARKER, msg_kwargs["body"])
        self.assertEqual(msg_kwargs["payload"]["question_budget"], 0)
        self.assertEqual(msg_kwargs["payload"]["interaction_mode"], "autonomous")
        task_kwargs = create_task.call_args.kwargs
        self.assertIn("autonomy:no-owner-questions-for-reversible-actions", task_kwargs["execution_policy"])
        self.assertEqual(task_kwargs["checklist"], ["Run tests", "Fix failures"])

    def test_interactive_override_preserves_human_in_loop_task(self):
        message_result = {"ok": True, "created": True, "message_id": "msg_interactive", "correlation_id": "corr-interactive"}
        task_result = {"ok": True, "created": True, "task_id": "ops_interactive", "correlation_id": "corr-interactive"}
        collection = MagicMock()
        with (
            patch("raphiia_openai.memory.agent_messages.create_agent_message", return_value=message_result) as create_message,
            patch("raphiia_openai.coordination_live.create_ops_task", return_value=task_result) as create_task,
            patch("raphiia_openai.mongo_store.get_db", return_value={"ralfia_agent_messages": collection}),
        ):
            coordination_ingest.ingest_agent_message(
                from_agent="CHATGPT",
                target_agent="codex",
                title="[P1] Deliberately interactive",
                body="Ask owner before choosing product direction",
                priority="p1",
                payload={"allow_owner_questions": True, "interaction_mode": "interactive"},
            )

        msg_kwargs = create_message.call_args.kwargs
        self.assertNotIn(policy.POLICY_MARKER, msg_kwargs["body"])
        self.assertIsNone(create_task.call_args.kwargs["execution_policy"])

    def test_normal_note_does_not_get_policy_injected(self):
        with (
            patch("raphiia_openai.memory.agent_messages.create_agent_message", return_value={"ok": True, "message_id": "msg_note"}) as create_message,
            patch("raphiia_openai.coordination_live.create_ops_task") as create_task,
        ):
            coordination_ingest.ingest_agent_message(
                from_agent="CHATGPT",
                target_agent="codex",
                title="Context only",
                body="This is not a task.",
            )
        self.assertNotIn(policy.POLICY_MARKER, create_message.call_args.kwargs["body"])
        create_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
