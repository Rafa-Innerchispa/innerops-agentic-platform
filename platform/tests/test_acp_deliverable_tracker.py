from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime.agents import ag58_acp_deliverable_tracker as ag58


class AcpDeliverableTrackerTests(unittest.TestCase):
    def test_capability_matrix_covers_four_ides(self) -> None:
        result = ag58.capability_matrix()
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 4)
        self.assertEqual(set(result["matrix"]), {"cursor", "codex", "antigravity", "gemini"})

    def test_cursor_is_native_acp(self) -> None:
        row = ag58.CAPABILITY_MATRIX["cursor"]
        self.assertEqual(row["acp_class"], ag58.ACP_NATIVE)
        self.assertIn(ag58.TRANSPORT_ACP, row["transports"])

    def test_antigravity_is_headless(self) -> None:
        row = ag58.CAPABILITY_MATRIX["antigravity"]
        self.assertEqual(row["acp_class"], ag58.ACP_HEADLESS)

    def test_uniform_transport_contract(self) -> None:
        contract = ag58.uniform_transport_contract(
            target="codex",
            correlation_id="corr-test",
            ops_task_id="ops_test",
            repo="Rafa-Innerchispa/innerops-agentic-platform",
            branch="cursor/acp-ide-fabric-20260828",
        )
        self.assertTrue(contract["ok"])
        self.assertEqual(contract["acp_class"], ag58.ACP_VERIFIED_ADAPTER)
        self.assertEqual(contract["metadata"]["correlation_id"], "corr-test")

    def test_delivery_never_equals_execution(self) -> None:
        correlated = ag58.correlate_a2a_acp(
            a2a_status={"status": {"state": "submitted"}, "correlation_id": "c1"},
            ops_status="proposed",
            target="cursor",
        )
        self.assertTrue(correlated["ok"])
        bridge = correlated["ide_task_bridge"]
        self.assertTrue(bridge["delivered_to_inbox"])
        self.assertFalse(bridge["completed"])
        self.assertEqual(bridge["execution_state"], "delivered_to_inbox")

    def test_running_is_distinct_from_delivered(self) -> None:
        correlated = ag58.correlate_a2a_acp(
            a2a_status={"status": {"state": "working"}},
            ops_status="in_progress",
            target="cursor",
        )
        bridge = correlated["ide_task_bridge"]
        self.assertTrue(bridge["running"])
        self.assertFalse(bridge["completed"])
        self.assertEqual(bridge["execution_state"], "running")

    def test_unsupported_target(self) -> None:
        contract = ag58.uniform_transport_contract(target="vscode")
        self.assertFalse(contract["ok"])
        self.assertEqual(contract["error"], "unsupported_target")

    def test_deliverable_status_partial(self) -> None:
        status = ag58.deliverable_status()
        self.assertEqual(status["status"], "PARTIAL")
        self.assertEqual(status["ops_task_id"], "ops_608d9780a8dd")
        self.assertIn("cursor", status["native_acp"])
        self.assertIn("cursor_acp_probe", status)
        if status.get("status") == "OK":
            self.assertEqual(status.get("blockers"), [])

    def test_cursor_acp_probe_reports_missing_cli(self) -> None:
        probe = ag58.probe_cursor_acp_surface()
        self.assertEqual(probe["probe"], "cursor_agent_acp")
        self.assertIn(probe.get("status"), {"PASS", "PARTIAL"})

    def test_verified_adapter_smoke_codex(self) -> None:
        smoke = ag58.verified_adapter_smoke(target="codex")
        self.assertTrue(smoke.get("ok"))
        self.assertEqual(smoke.get("acp_class"), ag58.ACP_VERIFIED_ADAPTER)


if __name__ == "__main__":
    unittest.main()
