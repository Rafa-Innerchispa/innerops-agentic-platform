"""Execution binding — fail-closed dispatch for IDE providers."""
from __future__ import annotations

import asyncio
import unittest

from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime import temporal_activities as ta


class ExecutionBindingTests(unittest.TestCase):
    def test_codex_internal_lane_blocked(self) -> None:
        binding = eb.resolve_execution_binding(
            {
                "task_id": "ops_e6cc30c1dd56",
                "preferred_provider": "codex",
                "execution_lane": "internal",
                "preferred_model": None,
            }
        )
        self.assertFalse(binding["allowed"])
        self.assertEqual(binding["error"], "interactive_provider_requires_ide_runner")

    def test_do_not_auto_dispatch_blocks(self) -> None:
        binding = eb.resolve_execution_binding(
            {
                "task_id": "ops_handoff",
                "assignee": "cursor",
                "payload": {"do_not_auto_dispatch": True, "dispatch_mode": "owner_interactive_handoff"},
            }
        )
        self.assertFalse(binding["allowed"])
        self.assertEqual(binding["status"], "waiting_for_binding")

    def test_model_preflight_missing_blocks(self) -> None:
        binding = eb.resolve_execution_binding(
            {
                "task_id": "ops_x",
                "preferred_provider": "codex",
                "execution_lane": "interactive_ide",
                "model_preflight_required": True,
                "preferred_model": None,
            }
        )
        self.assertFalse(binding["allowed"])
        self.assertEqual(binding["error"], "preferred_model_missing")

    def test_internal_dev_swarm_allowed(self) -> None:
        binding = eb.resolve_execution_binding(
            {
                "task_id": "ops_local",
                "preferred_provider": "dev_swarm",
                "execution_lane": "local_dev_swarm",
                "preferred_model": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ",
            }
        )
        self.assertTrue(binding["allowed"])
        self.assertEqual(binding["runner"], eb.INTERNAL_BOUNDED_RUNNER)

    def test_execute_agent_graph_does_not_run_bounded_when_blocked(self) -> None:
        envelope = {
            "task_id": "ops_blocked",
            "preferred_provider": "codex",
            "execution_lane": "internal",
            "task_class": "coding",
        }
        result = asyncio.run(ta.activity_execute_agent_graph(envelope, {"worktree": "/tmp/unused"}))
        self.assertTrue(result.get("blocked"))
        self.assertEqual(result.get("objective_files_count"), 0)
        self.assertIsNone(result["test_results"]["exit_code"])

    def test_completion_gate_reports_binding_block(self) -> None:
        agent_result = {
            "blocked": True,
            "execution_binding": {"message": "blocked for test"},
            "test_results": {"exit_code": None, "ok": False},
        }
        gate = asyncio.run(ta.activity_validate_completion_gate({"task_class": "coding"}, agent_result))
        self.assertFalse(gate.get("passed"))
        self.assertIn("blocked", gate.get("error", "").lower())


if __name__ == "__main__":
    unittest.main()
