"""Completion gate must resolve dotted evidence_required keys (e.g. test_results.exit_code)."""
from __future__ import annotations

import asyncio
import unittest

from inneros_core_runtime import temporal_activities as ta


class CompletionGateEvidenceKeysTests(unittest.TestCase):
    def test_dotted_test_results_exit_code_satisfies_requirement(self) -> None:
        envelope = {
            "task_class": "coding",
            "evidence_required": ["commit_sha", "objective_paths", "test_results.exit_code"],
            "execution_lane": "cursor_interactive",
        }
        agent_result = {
            "commit_sha": "a" * 40,
            "objective_paths": ["platform/foo.py"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
        }
        result = asyncio.run(ta.activity_validate_completion_gate(envelope, agent_result))
        self.assertTrue(result.get("passed"), result)


    def test_host_deploy_cannot_pass_with_generated_files_and_pytest_only(self) -> None:
        envelope = {
            "task_class": "coding",
            "execution_lane": "internal",
            "execution_policy": "owner-approved-bounded-platform-sync",
            "payload": {"rollback_required": True, "verify_dual_node": True},
            "title": "Deploy platform and restart runtime",
        }
        agent_result = {
            "ok": True,
            "files_count": 3,
            "objective_files_count": 3,
            "objective_paths": ["src/fake.py", "tests/fake_test.py", "package.json"],
            "code_diff": "+ fake",
            "test_results": {"exit_code": 0, "ok": True},
        }
        result = asyncio.run(ta.activity_validate_completion_gate(envelope, agent_result))
        self.assertFalse(result.get("passed"), result)
        self.assertIn("observed host mutation", result.get("error", ""))

    def test_host_deploy_requires_real_execution_and_postcondition_evidence(self) -> None:
        envelope = {
            "task_class": "deployment",
            "execution_lane": "internal",
            "execution_policy": "owner-approved-bounded-platform-sync",
            "payload": {"rollback_required": True, "verify_dual_node": True},
            "title": "Deploy platform and restart runtime",
        }
        agent_result = {
            "ok": True,
            "test_results": {"exit_code": 0, "ok": True},
            "host_execution": {
                "executed": True,
                "commands": ["git pull --ff-only", "systemctl --user restart inneros-mcp"],
                "before_sha": "a" * 40,
                "after_sha": "b" * 40,
            },
            "postconditions": {
                "verified": True,
                "service_health": {"amd": "healthy", "intel": "healthy"},
                "registry_resolution": {"ok": True},
            },
        }
        result = asyncio.run(ta.activity_validate_completion_gate(envelope, agent_result))
        self.assertTrue(result.get("passed"), result)


    def test_host_deploy_verification_sha_cannot_bypass_host_evidence(self) -> None:
        envelope = {
            "task_class": "verification",
            "execution_lane": "internal",
            "execution_policy": "owner-approved-bounded-platform-sync",
            "payload": {"rollback_required": True},
            "title": "Verify deployed runtime",
        }
        agent_result = {
            "ok": True,
            "commit_sha": "c" * 40,
            "test_results": {"exit_code": 0, "ok": True},
        }
        result = asyncio.run(ta.activity_validate_completion_gate(envelope, agent_result))
        self.assertFalse(result.get("passed"), result)
        self.assertIn("observed host mutation", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
