"""Comprehensive Unit Tests for Temporal Ops Engine with Docker Sandbox and LangGraph."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from inneros_core_runtime.docker_sandbox_executor import DockerSandboxExecutor
from inneros_core_runtime.temporal_activities import (
    AgentState,
    ProtocolMutationGuard,
    TaskEnvelopeV1,
    _build_langgraph_agent,
)


class TestDockerSandboxExecutor(unittest.TestCase):
    def test_sandbox_initialization(self):
        sandbox = DockerSandboxExecutor()
        self.assertEqual(sandbox.image, "inneros-sandbox:latest")
        self.assertEqual(sandbox.memory_limit, "2g")
        self.assertEqual(sandbox.cpus_limit, "1.5")
        self.assertEqual(sandbox.network, "none")

    def test_sandbox_run_command_nonexistent_worktree(self):
        sandbox = DockerSandboxExecutor()
        res = sandbox.run_command(cmd=["echo", "test"], worktree_path="/path/that/does/not/exist")
        self.assertFalse(res["ok"])
        self.assertIn("does not exist", res["stderr"])

    def test_sandbox_fallback_execution(self):
        sandbox = DockerSandboxExecutor()
        with TemporaryDirectory() as tmpdir:
            res = sandbox._run_fallback(
                cmd=["python3", "-c", "print('hello_sandbox')"],
                worktree=Path(tmpdir),
                env_vars={"FOO": "BAR"},
                timeout=10,
            )
            self.assertTrue(res["ok"])
            self.assertIn("hello_sandbox", res["stdout"])


class TestProtocolMutationGuard(unittest.TestCase):
    def test_terminal_immutability(self):
        envelope = TaskEnvelopeV1(task_id="ops_test_1", title="Test", status="completed", assignee="antigravity")
        res = ProtocolMutationGuard.validate_mutation(
            envelope=envelope,
            caller_agent="antigravity",
            acknowledged_revision=1,
        )
        self.assertFalse(res["allowed"])
        self.assertEqual(res["reason"], "TASK_TERMINAL")

    def test_pending_human_review_immutability(self):
        envelope = TaskEnvelopeV1(task_id="ops_test_2", title="Test", status="pending_human_review", assignee="antigravity")
        res = ProtocolMutationGuard.validate_mutation(
            envelope=envelope,
            caller_agent="antigravity",
            acknowledged_revision=1,
        )
        self.assertFalse(res["allowed"])
        self.assertEqual(res["reason"], "TASK_TERMINAL")

    def test_ownership_enforcement(self):
        envelope = TaskEnvelopeV1(task_id="ops_test_3", title="Test", status="in_progress", assignee="antigravity")
        res = ProtocolMutationGuard.validate_mutation(
            envelope=envelope,
            caller_agent="codex",
            acknowledged_revision=1,
        )
        self.assertFalse(res["allowed"])
        self.assertEqual(res["reason"], "TASK_NOT_ASSIGNED")

    def test_revision_stale_detection(self):
        envelope = TaskEnvelopeV1(task_id="ops_test_4", title="Test", status="in_progress", assignee="antigravity", revision=5)
        res = ProtocolMutationGuard.validate_mutation(
            envelope=envelope,
            caller_agent="antigravity",
            acknowledged_revision=4,
        )
        self.assertFalse(res["allowed"])
        self.assertEqual(res["reason"], "STALE_TASK_REVISION")

    def test_valid_mutation_allowed(self):
        envelope = TaskEnvelopeV1(task_id="ops_test_5", title="Test", status="in_progress", assignee="antigravity", revision=2)
        res = ProtocolMutationGuard.validate_mutation(
            envelope=envelope,
            caller_agent="antigravity",
            acknowledged_revision=2,
        )
        self.assertTrue(res["allowed"])
        self.assertEqual(res["reason"], "ALLOWED")


class TestLangGraphActorCritic(unittest.TestCase):
    def test_langgraph_compilation(self):
        graph = _build_langgraph_agent()
        self.assertIsNotNone(graph)

    @patch("inneros_core_runtime.local_model_router.run_local_model")
    def test_actor_critic_execution_pass(self, mock_model):
        mock_model.return_value = {
            "ok": True,
            "response": '{"summary": "fix", "files": [{"path": "dummy.py", "content": "print(1)"}]}',
        }
        graph = _build_langgraph_agent()
        self.assertIsNotNone(graph)

        with TemporaryDirectory() as tmpdir:
            initial_state: AgentState = {
                "task_id": "ops_test_pass",
                "objective": "Test task",
                "repo": "Rafa-Innerchispa/gitlab-contributorops-agent",
                "worktree": tmpdir,
                "phase": "plan",
                "plan": "",
                "code_diff": "",
                "files": [],
                "linter_results": {},
                "test_results": {},
                "error_count": 0,
                "max_errors": 3,
                "human_intervention_needed": False,
                "error": None,
                "success": False,
            }
            # Mock sandbox within evaluate node
            with patch.object(DockerSandboxExecutor, "run_command") as mock_sandbox:
                mock_sandbox.return_value = {"ok": True, "exit_code": 0, "stdout": "OK", "stderr": ""}
                res = graph.invoke(initial_state)
                self.assertTrue(res["success"])
                self.assertEqual(res["phase"], "done")


if __name__ == "__main__":
    unittest.main()
