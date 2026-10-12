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


if __name__ == "__main__":
    unittest.main()
