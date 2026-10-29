from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import codex_ops_runner as cx
from inneros_core_runtime import execution_binding as eb


class CodexOpsTests(unittest.TestCase):
    def test_codex_do_not_auto_awaiting_claim(self) -> None:
        b = eb.resolve_execution_binding(
            {
                "preferred_provider": "codex",
                "execution_lane": "codex_interactive",
                "do_not_auto_dispatch": True,
            }
        )
        self.assertFalse(b["allowed"])
        self.assertEqual(b["status"], "awaiting_codex_claim")

    def test_claim_returns_headless_spawn_key(self) -> None:
        """MCP codex_claim_ops_task must mirror interactive_ops_runner post-claim wiring."""
        claimed = {
            "task_id": "ops_cx_claim",
            "repo": "",
            "owner_authorized_at": "2026-01-01T00:00:00+00:00",
            "effective_model": cx.CODEX_PINNED_MODEL,
        }
        mock_col = MagicMock()
        mock_col.find_one.side_effect = [claimed, claimed]
        mock_col.find_one_and_update.return_value = claimed
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_col
        with patch.object(cx.mongo_store, "get_db", return_value=mock_db):
            with patch.object(cx, "heartbeat_ops_task"):
                with patch("inneros_core_runtime.durable_coordination_spine.signal_task_workflow", return_value={"ok": True}):
                    with patch("inneros_core_runtime.codex_headless_dispatch.spawn_headless_execute", return_value={"ok": True, "pid": 1}) as spawn:
                        out = cx.claim_ops_task(task_id="ops_cx_claim", owner_approved=True)
        self.assertTrue(out.get("ok"))
        self.assertIn("headless_spawn", out)
        spawn.assert_called_once_with("ops_cx_claim")

    def test_complete_rejects_empty_evidence(self) -> None:
        task = {
            "task_id": "ops_cx",
            "claim_token": "t",
            "assignee": "codex",
            "lease_until": "2099-01-01T00:00:00+00:00",
            "effective_model": cx.CODEX_PINNED_MODEL,
        }
        mock_col = MagicMock()
        mock_col.find_one.return_value = task
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_col
        with patch.object(cx.mongo_store, "get_db", return_value=mock_db):
            out = cx.complete_ops_task("ops_cx", claim_token="t", evidence={})
        self.assertFalse(out.get("ok"))


if __name__ == "__main__":
    unittest.main()
