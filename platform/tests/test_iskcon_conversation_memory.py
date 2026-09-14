from __future__ import annotations

import unittest
from unittest.mock import patch

from raphiia_openai import iskcon_conversation_memory as icm


class TestIskconConversationMemory(unittest.TestCase):
    def test_build_payload_routes_iskcon_with_project_entity_and_provenance(self) -> None:
        payload = icm.build_conversation_payload(
            conversation_id="conv-iskcon-1",
            messages=[
                {
                    "message_id": "m1",
                    "role": "user",
                    "content": "Necesito guardar la clase de Bhagavad-gita de ISKCON Guayaquil.",
                }
            ],
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["project"], "iskcon")
        self.assertEqual(payload["metadata"]["entity_id"], "ent_iskcon")
        self.assertEqual(payload["messages"][0]["source_message_id"], "m1")
        self.assertEqual(payload["messages"][0]["metadata"]["project"], "iskcon")
        self.assertIn("bhagavad", payload["metadata"]["matched_keywords"])

    def test_non_iskcon_conversation_is_not_captured_without_force(self) -> None:
        payload = icm.build_conversation_payload(
            conversation_id="conv-other",
            messages=[{"role": "user", "content": "Revisar una cotización de PC Doctor."}],
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "not_iskcon_conversation")

    def test_relevant_messages_prevent_mixed_conversation_contamination(self) -> None:
        selected = icm.relevant_messages(
            [
                {"message_id": "private", "content": "Contenido personal que no pertenece al proyecto."},
                {"message_id": "iskcon", "content": "Planificar Panihati y Food for Life con ISKCON."},
            ]
        )

        self.assertEqual([item["message_id"] for item in selected], ["iskcon"])

    def test_save_and_finalize_preserves_ent_iskcon_in_analysis_items(self) -> None:
        saved = {"ok": True, "inserted": 1, "received": 1}
        finalized = {"ok": True, "result": {"memory_ids": ["mem1"]}}

        with patch.object(icm.daily_memory, "save_conversation_batch", return_value=saved) as save, patch.object(
            icm.daily_memory, "finalize_conversation", return_value=finalized
        ) as finalize:
            result = icm.save_and_finalize_conversation(
                conversation_id="conv-panihati",
                messages=[
                    {
                        "message_id": "m1",
                        "role": "user",
                        "content": "Hoy hice seguimiento del festival Panihati y queda pendiente revisar voluntarios.",
                    }
                ],
                dry_run=False,
            )

        self.assertTrue(result["ok"])
        save_payload = save.call_args.args[0]
        finalize_payload = finalize.call_args.args[0]
        self.assertEqual(save_payload["project"], "iskcon")
        self.assertEqual(finalize_payload["project"], "iskcon")
        self.assertEqual(finalize_payload["state_key"], "project:iskcon")
        pending = finalize_payload["analysis"]["pending"][0]
        self.assertEqual(pending["entities"], ["ent_iskcon"])
        self.assertEqual(pending["metadata"]["entity_id"], "ent_iskcon")

    def test_search_uses_project_and_entity_filter_first(self) -> None:
        with patch.object(icm.daily_memory, "search_memory", return_value={"ok": True, "count": 1, "items": [{"memory_id": "mem1"}]}) as search:
            result = icm.search_iskcon_memory("Panihati", actor="RAFAEL")

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        args = search.call_args.args[0]
        self.assertEqual(args["project"], "iskcon")
        self.assertEqual(args["entity_id"], "ent_iskcon")
        self.assertIn("PROJECT", args["allowed_privacy"])

    def test_hector_gap_is_explicit_without_fabrication(self) -> None:
        with patch.object(icm.daily_memory, "search_memory", return_value={"ok": True, "count": 0, "items": []}):
            result = icm.hector_context_status()

        self.assertEqual(result["status"], "GAP")
        self.assertIn("no se fabrica contenido", result["message"])


if __name__ == "__main__":
    unittest.main()
