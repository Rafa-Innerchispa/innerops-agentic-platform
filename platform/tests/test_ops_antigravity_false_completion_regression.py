"""Regression: ops_64d4bf6d941e false COMPLETED via text-only Antigravity Gemini API."""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from inneros_core_runtime import ops_completion_policy as ocp
from inneros_core_runtime import temporal_activities as ta
from inneros_core_runtime.execution_receipts import git_head

NEBius_SHA = "b90b8e0781b6ddbe4dfdb0ecf57071396000682c"
REGRESSION_TASK = {
    "task_id": "ops_64d4bf6d941e",
    "task_class": "coding",
    "title": "Hosting pcdoctor.ai / pcdoctor.com.ec",
    "objective": "Deploy landing WordPress cPanel hosting allowlist pcdoctor.ai pcdoctor.com.ec",
    "repo": "Rafa-Innerchispa/innerops-agentic-platform",
}


def _intel_log_evidence() -> dict:
    return {
        "headless_primary": "antigravity_gemini_api",
        "pinned_model_policy": "gemini-3.7-flash-medium",
        "gemini_model": "gemini-3.6-flash",
        "summary": "Plan ejecutado en InnerOS (Antigravity)",
        "notes": "antigravity_headless_execute_one",
        "objective_files_count": 1,
        "objective_paths": ["platform/docs/ANTIGRAVITY_HEADLESS_64d4bf6d941e.md"],
        "commit_sha": NEBius_SHA,
        "test_results": {},
        "code_diff": "",
    }


class AntigravityFalseCompletionRegressionTests(unittest.TestCase):
    def test_text_only_headless_evidence_rejected(self) -> None:
        err = ocp.validate_mutating_completion_evidence(REGRESSION_TASK, _intel_log_evidence())
        self.assertIsNotNone(err)
        self.assertIn("text_only", err)

    def test_empty_test_results_rejected(self) -> None:
        ev = dict(_intel_log_evidence())
        ev.pop("headless_primary")
        plain_coding = {"task_class": "coding", "objective": "fix unit test in platform module"}
        err = ocp.validate_mutating_completion_evidence(plain_coding, ev)
        self.assertIsNotNone(err)
        self.assertIn("exit_code", err)

    def test_deployment_objective_requires_host_mutation(self) -> None:
        ev = {
            "commit_sha": NEBius_SHA,
            "objective_paths": ["platform/docs/x.md"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
        }
        err = ocp.validate_mutating_completion_evidence(REGRESSION_TASK, ev)
        self.assertEqual(err, "deployment_requires_observed_host_mutation")

    def test_temporal_gate_rejects_intel_log_agent_result(self) -> None:
        agent = {
            **_intel_log_evidence(),
            "completion_channel": "antigravity_interactive",
            "ok": True,
        }
        gate = asyncio.run(ta.activity_validate_completion_gate(REGRESSION_TASK, agent))
        self.assertFalse(gate["passed"])
        err_l = gate["error"].lower()
        self.assertTrue("text_only" in err_l or "host/deployment" in err_l or "deployment" in err_l)

    def test_temporal_gate_rejects_text_only_on_plain_coding(self) -> None:
        agent = {
            "headless_primary": "antigravity_gemini_api",
            "commit_sha": NEBius_SHA,
            "objective_paths": ["x.py"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
            "completion_channel": "antigravity_interactive",
        }
        env = {"task_class": "coding", "objective": "patch helper"}
        gate = asyncio.run(ta.activity_validate_completion_gate(env, agent))
        self.assertFalse(gate["passed"])
        self.assertIn("text_only", gate["error"].lower())

    def test_foreign_sha_without_worktree_receipt_rejected(self) -> None:
        ev = {
            "commit_sha": NEBius_SHA,
            "objective_paths": ["platform/docs/marker.md"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
            "host_execution": {"executed": True},
            "postconditions": {"verified": True},
        }
        err = ocp.validate_mutating_completion_evidence({"task_class": "coding", "objective": "fix bug"}, ev)
        self.assertIn("git_baseline", err)

    def test_canary_real_commit_passes_with_receipt(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
        baseline = git_head(repo)
        (repo / "platform").mkdir()
        (repo / "platform" / "docs").mkdir()
        marker = repo / "platform" / "docs" / "CURSOR_CANARY.md"
        marker.write_text("canary\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "platform/docs/CURSOR_CANARY.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "canary"], check=True)
        head = git_head(repo)
        ev = {
            "commit_sha": head,
            "objective_paths": ["platform/docs/CURSOR_CANARY.md"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
            "evidence_source": "git_committed_diff_on_execution_host",
            "git_before_sha": baseline,
        }
        task = {"task_class": "coding", "objective": "add canary doc only"}
        err = ocp.validate_mutating_completion_evidence(task, ev, worktree=repo, before_sha=baseline)
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
