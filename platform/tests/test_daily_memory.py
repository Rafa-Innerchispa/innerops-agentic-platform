from __future__ import annotations

import unittest

from raphiia_openai import daily_memory
from raphiia_openai.auth_middleware import TOOL_SCOPES


class DailyMemoryPolicyTests(unittest.TestCase):
    def test_privacy_taxonomy_is_complete(self) -> None:
        self.assertEqual(
            daily_memory.PRIVACY_SCOPES,
            {
                "PRIVATE_PERSONAL",
                "PRIVATE_HEALTH",
                "PRIVATE_RELATIONSHIPS",
                "PRIVATE_FAMILY",
                "PRIVATE_FINANCIAL",
                "INTERNAL_WORK",
                "PROJECT",
                "PUBLIC",
            },
        )

    def test_sensitive_content_cannot_be_public(self) -> None:
        with self.assertRaisesRegex(ValueError, "privacy_mismatch"):
            daily_memory._privacy_guard("Mi diagnóstico médico cambió", "PUBLIC")

    def test_non_owner_cannot_request_private_scope(self) -> None:
        allowed = daily_memory._allowed("CODEX", ["PRIVATE_PERSONAL", "PROJECT"])
        self.assertEqual(allowed, {"PROJECT"})

    def test_daily_memory_tools_use_least_privilege_scopes(self) -> None:
        self.assertEqual(TOOL_SCOPES["get_current_state"], ["ralfia:memory:read", "ralfia:private_memory"])
        self.assertEqual(TOOL_SCOPES["search_memory"], ["ralfia:memory:read", "ralfia:private_memory"])
        self.assertEqual(TOOL_SCOPES["timeline"], ["ralfia:memory:read", "ralfia:private_memory"])
        self.assertEqual(TOOL_SCOPES["save_conversation_batch"], ["ralfia:memory:write", "ralfia:private_memory"])
        self.assertEqual(TOOL_SCOPES["finalize_conversation"], ["ralfia:memory:finalize", "ralfia:private_memory"])

    def test_deterministic_analysis_separates_claim_types(self) -> None:
        messages = [
            {"role": "user", "message_id": "m1", "content": "Hoy fui a una reunión. Creo que salió bien. Tal vez aprobemos el proyecto. Interpreto que falta evidencia. Decidí documentarlo. Queda pendiente revisar."}
        ]
        analysis = daily_memory._deterministic_analysis(messages)
        self.assertTrue(analysis["facts"])
        self.assertTrue(analysis["opinions"])
        self.assertTrue(analysis["hypotheses"])
        self.assertTrue(analysis["interpretations"])
        self.assertTrue(analysis["decisions"])
        self.assertTrue(analysis["pending"])

    def test_unmarked_statement_is_not_promoted_to_fact(self) -> None:
        analysis = daily_memory._deterministic_analysis(
            [{"role": "user", "message_id": "m1", "content": "La otra persona quiso atacarme"}]
        )
        self.assertFalse(analysis["facts"])
        self.assertEqual(analysis["interpretations"][0]["confidence_basis"], "ambiguous_unmarked_statement")
        self.assertLess(analysis["interpretations"][0]["confidence"], 0.5)

    def test_intention_is_distinct_from_decision(self) -> None:
        analysis = daily_memory._deterministic_analysis(
            [{"role": "user", "message_id": "m1", "content": "Quiero escribir un diario. Decidí empezar hoy."}]
        )
        self.assertEqual(len(analysis["intentions"]), 1)
        self.assertEqual(len(analysis["decisions"]), 1)
        self.assertFalse(analysis["facts"])

    def test_explicit_relational_correction_becomes_validated_rule(self) -> None:
        analysis = daily_memory._deterministic_analysis(
            [
                {
                    "role": "user",
                    "message_id": "m1",
                    "content": "Entre nosotros, código azul es humor interno y no significa agresión.",
                }
            ]
        )
        rule = analysis["context_rules"][0]
        self.assertTrue(rule["owner_validated"])
        self.assertEqual(rule["confidence"], 1.0)
        self.assertFalse(analysis["facts"])

    def test_single_session_pattern_needs_review(self) -> None:
        analysis = daily_memory._deterministic_analysis(
            [{"role": "user", "message_id": "m1", "content": "He notado un patrón: siempre me pasa al final del día."}]
        )
        candidate = analysis["pattern_candidates"][0]
        self.assertTrue(candidate["metadata"]["requires_review"])
        self.assertTrue(candidate["metadata"]["not_a_diagnosis"])
        self.assertFalse(
            daily_memory._pattern_is_supported(
                {"conversation_id": "conv_one", "owner_validated": False}
            )
        )
        self.assertTrue(
            daily_memory._pattern_is_supported(
                {"source_conversation_ids": ["conv_one", "conv_two"]}
            )
        )

    def test_epistemic_confidence_is_clamped_and_owner_confirmation_wins(self) -> None:
        inferred = daily_memory._epistemic_values("interpretation", {"confidence": 3})
        self.assertEqual(inferred["confidence"], 1.0)
        self.assertEqual(inferred["confidence_label"], "high")
        confirmed = daily_memory._epistemic_values(
            "context_rule", {"confidence": 0.1, "owner_validated": True}
        )
        self.assertEqual(confirmed["confidence"], 1.0)
        self.assertEqual(confirmed["confidence_label"], "owner_confirmed")


if __name__ == "__main__":
    unittest.main()
