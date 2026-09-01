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


if __name__ == "__main__":
    unittest.main()
