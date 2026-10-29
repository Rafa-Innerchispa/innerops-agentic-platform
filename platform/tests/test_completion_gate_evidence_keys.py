"""Completion gate must resolve dotted evidence_required keys (e.g. test_results.exit_code)."""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from inneros_core_runtime import temporal_activities as ta
from inneros_core_runtime.execution_receipts import git_head


def _temp_git_repo_with_commit() -> tuple[tempfile.TemporaryDirectory, Path, str, str, list[str]]:
    tmp = tempfile.TemporaryDirectory()
    repo = Path(tmp.name)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    baseline = git_head(repo)
    (repo / "platform").mkdir()
    (repo / "platform" / "foo.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "platform/foo.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "feature"], check=True)
    head = git_head(repo)
    return tmp, repo, baseline, head, ["platform/foo.py"]


class CompletionGateEvidenceKeysTests(unittest.TestCase):
    def test_dotted_test_results_exit_code_satisfies_requirement(self) -> None:
        tmp, repo, baseline, head, paths = _temp_git_repo_with_commit()
        self.addCleanup(tmp.cleanup)
        envelope = {
            "task_class": "coding",
            "evidence_required": ["commit_sha", "objective_paths", "test_results.exit_code"],
            "execution_lane": "cursor_interactive",
            "git_baseline_sha": baseline,
        }
        agent_result = {
            "commit_sha": head,
            "objective_paths": paths,
            "objective_files_count": len(paths),
            "test_results": {"exit_code": 0, "ok": True},
            "git_before_sha": baseline,
            "worktree": str(repo),
            "completion_channel": "cursor_interactive",
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
            "payload": {
                "rollback_required": True,
                "verify_dual_node": True,
                "deploy_approved_at": "2026-10-29T12:00:00+00:00",
            },
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
