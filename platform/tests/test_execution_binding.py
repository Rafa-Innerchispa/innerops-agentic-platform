"""Execution binding — fail-closed dispatch for IDE providers."""
from __future__ import annotations

import asyncio
import unittest

from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime import agent_provider_registry as apr
from inneros_core_runtime import temporal_activities as ta


class ExecutionBindingTests(unittest.TestCase):
    def test_antigravity_internal_lane_blocked(self) -> None:
        binding = eb.resolve_execution_binding(
            {
                "task_id": "ops_ag",
                "preferred_provider": "antigravity",
                "execution_lane": "internal",
            }
        )
        self.assertFalse(binding["allowed"])
        self.assertEqual(binding["error"], "interactive_provider_requires_ide_runner")

    def test_antigravity_handoff_awaiting_claim(self) -> None:
        binding = eb.resolve_execution_binding(
            {
                "task_id": "ops_ag2",
                "preferred_provider": "antigravity",
                "execution_lane": "antigravity_interactive",
                "do_not_auto_dispatch": True,
            }
        )
        self.assertFalse(binding["allowed"])
        self.assertEqual(binding["status"], "awaiting_antigravity_claim")
        self.assertEqual(binding["error"], "antigravity_claim_required")

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
        self.assertEqual(binding["status"], "awaiting_cursor_claim")

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

    def test_owner_summary_explains_codex_not_internal(self) -> None:
        env = {
            "task_id": "ops_x",
            "title": "Fix bridge",
            "preferred_provider": "codex",
            "execution_lane": "internal",
            "correlation_id": "corr-1",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        }
        binding = eb.resolve_execution_binding(env)
        summary = eb.owner_execution_summary(env, binding)
        self.assertFalse(binding["allowed"])
        self.assertIn("IDE", summary["why_not_internal"])
        self.assertTrue(summary["requires_owner_authorization"])
        self.assertIn("Dev Swarm", summary["internal_alternative"])

    def test_local_amd_and_intel_internal_defaults_match_binding(self) -> None:
        for provider in ("local-amd-5", "local-intel-4"):
            with self.subTest(provider=provider):
                lane, effective_provider, no_auto = apr.apply_create_ops_defaults(
                    "dev_swarm", execution_lane=None, preferred_provider=provider,
                    do_not_auto_dispatch=None,
                )
                self.assertEqual(lane, "local_dev_swarm")
                self.assertFalse(no_auto)
                self.assertIn(effective_provider, apr.internal_providers())
                binding = eb.resolve_execution_binding({
                    "task_id": "ops_local_symmetry",
                    "preferred_provider": provider,
                    "repo": "Rafa-Innerchispa/innerops-agentic-platform",
                })
                self.assertTrue(binding["allowed"], binding)
                self.assertEqual(binding["runner"], eb.INTERNAL_BOUNDED_RUNNER)

    def test_registered_internal_provider_binds_without_hardcoded_list(self) -> None:
        apr.register_internal_provider("local-test-edge")
        binding = eb.resolve_execution_binding({
            "task_id": "ops_new_internal",
            "preferred_provider": "local-test-edge",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        })
        self.assertTrue(binding["allowed"], binding)
        lane, _, no_auto = apr.apply_create_ops_defaults(
            "dev_swarm", execution_lane=None,
            preferred_provider="local-test-edge", do_not_auto_dispatch=None,
        )
        self.assertEqual(lane, "local_dev_swarm")
        self.assertFalse(no_auto)

    def test_owner_explicit_no_autodispatch_not_overridden(self) -> None:
        lane, _, no_auto = apr.apply_create_ops_defaults(
            "dev_swarm", execution_lane=None,
            preferred_provider="local-intel-4", do_not_auto_dispatch=True,
        )
        self.assertEqual(lane, "local_dev_swarm")
        self.assertTrue(no_auto)
        binding = eb.resolve_execution_binding({
            "task_id": "ops_intel_blocked",
            "preferred_provider": "local-intel-4",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "do_not_auto_dispatch": True,
        })
        self.assertFalse(binding["allowed"])
        self.assertEqual(binding["error"], "do_not_auto_dispatch")

    def test_internal_dev_swarm_allowed(self) -> None:
        binding = eb.resolve_execution_binding(
            {
                "task_id": "ops_local",
                "preferred_provider": "dev_swarm",
                "execution_lane": "local_dev_swarm",
                "preferred_model": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ",
                "repo": "Rafa-Innerchispa/innerops-agentic-platform",
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
