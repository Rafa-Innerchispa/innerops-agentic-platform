"""Cursor ops claim — owner gate + model pin."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from inneros_core_runtime import cursor_ops_runner as cor


class CursorOpsRunnerTests(unittest.TestCase):
    def test_claim_requires_owner_approval(self) -> None:
        fake_task = {
            "task_id": "ops_test1",
            "title": "T",
            "status": "waiting_for_binding",
            "assignee": "cursor",
        }
        mock_col = MagicMock()
        mock_col.find_one.return_value = fake_task
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_col
        with (
            patch.object(cor.cep, "register_session_heartbeat", return_value={"ok": True}),
            patch.object(cor.cep, "classify_cursor_execution", return_value={"execution_classification": "partial"}),
            patch.object(cor.mongo_store, "get_db", return_value=mock_db),
        ):
            out = cor.claim_ops_task(task_id="ops_test1", owner_approved=False)
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "owner_approval_required")

    def test_pinned_model_constant(self) -> None:
        self.assertIn("composer", cor.CURSOR_PINNED_MODEL.lower())


if __name__ == "__main__":
    unittest.main()
