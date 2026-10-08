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

    def test_complete_rejects_empty_evidence(self) -> None:
        task = {
            "task_id": "ops_x",
            "claim_token": "tok",
            "lease_until": "2099-01-01T00:00:00+00:00",
            "effective_model": cor.CURSOR_PINNED_MODEL,
        }
        mock_col = MagicMock()
        mock_col.find_one.return_value = task
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_col
        with patch.object(cor.mongo_store, "get_db", return_value=mock_db):
            out = cor.complete_ops_task("ops_x", claim_token="tok", status="completed", evidence={})
        self.assertFalse(out.get("ok"))
        self.assertIn("evidence", str(out.get("error")))

    def test_complete_rejects_expired_lease(self) -> None:
        task = {
            "task_id": "ops_x",
            "claim_token": "tok",
            "lease_until": "2000-01-01T00:00:00+00:00",
            "effective_model": cor.CURSOR_PINNED_MODEL,
        }
        mock_col = MagicMock()
        mock_col.find_one.return_value = task
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_col
        with patch.object(cor.mongo_store, "get_db", return_value=mock_db):
            out = cor.complete_ops_task(
                "ops_x",
                claim_token="tok",
                evidence={"commit_sha": "abc123", "objective_files_count": 1, "objective_paths": ["a.py"]},
            )
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "lease_expired")

    def test_binding_after_claim_not_awaiting_again(self) -> None:
        from inneros_core_runtime import execution_binding as eb

        binding = eb.resolve_execution_binding(
            {
                "task_id": "ops_c",
                "status": "claimed",
                "claim_token": "abc",
                "preferred_provider": "cursor",
                "do_not_auto_dispatch": True,
                "preferred_model": cor.CURSOR_PINNED_MODEL,
                "effective_model": cor.CURSOR_PINNED_MODEL,
            }
        )
        self.assertNotEqual(binding.get("status"), "awaiting_cursor_claim")
        self.assertTrue(binding.get("interactive_execution"))


if __name__ == "__main__":
    unittest.main()
