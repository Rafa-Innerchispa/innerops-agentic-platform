from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Force this isolated worktree's platform package ahead of the live runtime copy.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime import agent_autonomy_policy as policy


class AgentAutonomyPolicyTests(unittest.TestCase):
    def test_default_policy_has_zero_question_budget(self):
        meta = policy.metadata()
        self.assertEqual(meta["question_budget"], 0)
        self.assertTrue(meta["retry_policy"]["automatic"])
        self.assertEqual(meta["retry_policy"]["minimum_safe_fallbacks_before_blocked"], 1)
        self.assertFalse(meta["ack_is_execution"])

    def test_reversible_work_does_not_interrupt_owner(self):
        self.assertFalse(policy.can_interrupt_owner("run_tests"))
        self.assertFalse(policy.can_interrupt_owner("create_worktree"))
        self.assertFalse(policy.can_interrupt_owner("commit_own_branch"))
        self.assertTrue(policy.can_interrupt_owner("destructive_or_irreversible"))
        self.assertTrue(policy.can_interrupt_owner("unavailable_secret_or_credential"))

    def test_body_enrichment_is_idempotent(self):
        first = policy.enrich_body("Do the task", target="codex", payload={})
        second = policy.enrich_body(first, target="codex", payload={})
        self.assertIn(policy.POLICY_MARKER, first)
        self.assertEqual(first, second)
        self.assertIn("question_budget=0", first)
        self.assertIn("ACK/read receipt is not execution", first)

    def test_interactive_override_disables_default_autonomy_injection(self):
        payload = {"allow_owner_questions": True}
        body = policy.enrich_body("Ask when uncertain", target="codex", payload=payload)
        self.assertEqual(body, "Ask when uncertain")
        self.assertNotIn(policy.POLICY_MARKER, body)

    def test_non_ide_target_is_not_modified(self):
        body = policy.enrich_body("Normal task", target="chatgpt", payload={})
        self.assertEqual(body, "Normal task")


if __name__ == "__main__":
    unittest.main()
