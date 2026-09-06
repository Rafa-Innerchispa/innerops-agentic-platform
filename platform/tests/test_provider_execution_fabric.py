from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime import provider_execution_fabric as fabric


class ProviderExecutionFabricTests(unittest.TestCase):
    def test_contract_names_required_provider_methods(self):
        contract = fabric.provider_contract()

        self.assertTrue(contract["ok"])
        self.assertIn("launch", contract["provider_adapter_methods"])
        self.assertIn("collect_evidence", contract["provider_adapter_methods"])
        self.assertIn("process", contract["running_requires"])
        self.assertIn("remote_session", contract["running_requires"])

    def test_running_requires_execution_proof(self):
        result = fabric.validate_execution_proof("codex", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "execution_proof_required")

    def test_process_proof_requires_pid(self):
        result = fabric.validate_execution_proof("codex", {"proof_type": "process", "pid": 0})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "process_pid_required")

    def test_remote_session_proof_requires_transport(self):
        result = fabric.validate_execution_proof("cursor", {"proof_type": "remote_session", "session_id": "sess-1", "transport": "a2a"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "cursor")

    @patch("inneros_core_runtime.provider_execution_fabric._detect_manifest_provider")
    def test_future_provider_can_register_by_manifest(self, detect_manifest):
        detect_manifest.return_value = {"ok": True, "provider": "futureai", "status": "manifest_registered"}

        result = fabric.detect_provider("futureai")

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "futureai")

    @patch("inneros_core_runtime.provider_execution_fabric.ide_task_bridge.dispatch_task")
    @patch("inneros_core_runtime.provider_execution_fabric.detect_provider")
    def test_execute_provider_task_blocks_without_executable_provider(self, detect_provider, dispatch_task):
        detect_provider.return_value = {"ok": True, "provider": "codex", "status": "remote_inbox_only", "headless_supported": False}
        dispatch_task.return_value = {"ok": True, "dispatch_id": "ide_1", "execution_state": "queued"}

        result = fabric.execute_provider_task(provider="codex", title="T", body="B", dry_run=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["execution_state"], "blocked")
        self.assertEqual(result["error"], "provider_not_executable_on_this_node")

    @patch("inneros_core_runtime.provider_execution_fabric.ide_task_bridge.complete_task")
    @patch("inneros_core_runtime.provider_execution_fabric.mark_running_with_proof")
    @patch("inneros_core_runtime.provider_execution_fabric.subprocess.Popen")
    def test_codex_smoke_invokes_codex_cli_without_prompt(self, popen, mark_running, complete_task):
        proc = Mock()
        proc.pid = 12345
        proc.returncode = 0
        proc.communicate.return_value = ("codex-cli 0.139.0\n", "")
        popen.return_value = proc
        mark_running.return_value = {"ok": True, "execution_state": "running"}
        complete_task.return_value = {"ok": True, "execution_state": "completed"}

        result = fabric._execute_codex_smoke(
            {"dispatch_id": "ide_1", "worktree": str(Path.cwd())},
            {"cli_path": "/usr/local/bin/codex"},
        )

        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["/usr/local/bin/codex", "--version"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["evidence"]["process"]["pid"], 12345)
        self.assertIn("codex-cli", result["evidence"]["process"]["stdout_tail"])

    def test_local_qwen_alias_detects_canonical_provider(self):
        with patch("inneros_core_runtime.provider_execution_fabric.local_model_router.classify_task_runtime") as classify, patch("inneros_core_runtime.provider_execution_fabric.local_model_router.local_model_health") as health:
            classify.return_value = {"recommended_provider": "local-amd-5", "recommended_model": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ", "recommended_backend": "vllm"}
            health.return_value = {"ok": True, "vllm": {"api_models": {"ok": True}}}
            result = fabric.detect_provider("local-amd-5")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "local_qwen")
        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["remote_inbox_supported"])

    def test_local_qwen_file_ops_rejects_unsafe_paths(self):
        files, rejected = fabric._safe_file_ops({"files": [
            {"action": "write", "path": "platform/tests/test_ok.py", "content": "def test_ok():\n    assert True\n"},
            {"action": "write", "path": "../outside.py", "content": "bad"},
            {"action": "delete", "path": "platform/tests/no.py", "content": "bad"},
        ]})
        self.assertEqual([f["path"] for f in files], ["platform/tests/test_ok.py"])
        self.assertEqual(len(rejected), 2)

    @patch("inneros_core_runtime.provider_execution_fabric.local_execution_plane.release_lock")
    @patch("inneros_core_runtime.provider_execution_fabric.local_execution_plane.commit_branch")
    @patch("inneros_core_runtime.provider_execution_fabric.local_execution_plane.run_command_allowlisted")
    @patch("inneros_core_runtime.provider_execution_fabric.local_execution_plane.write_file")
    @patch("inneros_core_runtime.provider_execution_fabric._model_file_ops")
    @patch("inneros_core_runtime.provider_execution_fabric.local_execution_plane.create_worktree")
    @patch("inneros_core_runtime.provider_execution_fabric.local_execution_plane.acquire_lock")
    def test_local_qwen_executes_bounded_write_tests_and_commit(self, acquire_lock, create_worktree, model_file_ops, write_file, run_cmd, commit_branch, release_lock):
        acquire_lock.return_value = {"ok": True, "lock_id": "lock-1"}
        create_worktree.return_value = {"ok": True, "worktree": "/tmp/wt"}
        model_file_ops.return_value = (
            {"ok": True, "last": {"selected_model": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ", "provider_id": "local-amd-5", "runtime": "local_vllm"}},
            [{"path": "platform/tests/test_local_qwen_fileops_smoke.py", "content": "def test_smoke():\n    assert True\n"}],
            [],
        )
        write_file.return_value = {"ok": True, "path": "platform/tests/test_local_qwen_fileops_smoke.py"}
        run_cmd.return_value = {"ok": True, "command_result": {"ok": True, "returncode": 0}}
        commit_branch.return_value = {"ok": True, "head": "abc123"}

        result = fabric._execute_local_qwen_fileops(
            title="smoke", body="create harmless fixture", repo="Rafa-Innerchispa/innerops-agentic-platform", base_ref="main", work_branch="local-agent/smoke",
            correlation_id="corr", from_agent="CHATGPT", idempotency_key="idem",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["proof_valid"]["proof_type"], "local_model")
        write_file.assert_called_once()
        run_cmd.assert_called_once()
        commit_branch.assert_called_once()
        release_lock.assert_called_once()

    @patch("inneros_core_runtime.provider_execution_fabric.ide_task_bridge.dispatch_task")
    @patch("inneros_core_runtime.provider_execution_fabric.detect_provider")
    def test_cursor_remains_remote_inbox_truth_not_fake_running(self, detect_provider, dispatch_task):
        detect_provider.return_value = {"ok": True, "provider": "cursor", "status": "remote_inbox_only", "remote_inbox_supported": True}
        dispatch_task.return_value = {"ok": True, "dispatch_id": "ide_cursor", "execution_state": "queued"}
        result = fabric.execute_provider_task(provider="cursor", title="T", body="B", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["execution_state"], "queued")



if __name__ == "__main__":
    unittest.main()
