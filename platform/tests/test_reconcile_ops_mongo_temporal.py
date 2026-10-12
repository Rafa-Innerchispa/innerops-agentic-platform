"""Regression tests for safe Temporal -> Mongo task reconciliation."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_ops_mongo_temporal.py"
_spec = importlib.util.spec_from_file_location("inneros_reconcile_ops_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
reconcile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reconcile)


class ReconcileSafetyTests(unittest.TestCase):
    def setUp(self):
        self.task = {"task_id": "ops_test", "status": "in_progress", "task_class": "coding"}

    def check(self, temporal):
        return reconcile._proposed_action(self.task, temporal)

    def test_temporal_completes_but_workflow_returns_failed(self):
        p = self.check({"ok": True, "terminal": True,
            "status": "WorkflowExecutionStatus.COMPLETED", "result_status": "failed"})
        self.assertEqual(p["new_status"], "failed")

    def test_temporal_completed_without_business_result_cannot_pass(self):
        self.assertIsNone(self.check({"ok": True, "terminal": True,
            "status": "WorkflowExecutionStatus.COMPLETED"}))

    def test_temporal_business_completed_requires_coding_gate(self):
        t = {"ok": True, "terminal": True,
            "status": "WorkflowExecutionStatus.COMPLETED",
            "result_status": "completed", "result_gate_passed": None}
        self.assertIsNone(self.check(t))
        t["result_gate_passed"] = True
        self.assertEqual(self.check(t)["new_status"], "completed")

    def test_verification_task_does_not_require_coding_diff(self):
        self.task["task_class"] = "verification"
        p = self.check({"ok": True, "terminal": True,
            "status": "WorkflowExecutionStatus.COMPLETED", "result_status": "completed"})
        self.assertEqual(p["new_status"], "completed")

    def test_temporal_backend_failure_never_kills_leased_task(self):
        self.task["lease_until"] = "2020-01-01T00:00:00+00:00"
        self.task["headless_execution_finished_at"] = "2020-01-01T00:00:00+00:00"
        self.assertIsNone(self.check({"ok": False, "error": "ConnectionError"}))

    def test_temporal_failure_propagates_as_failure(self):
        p = self.check({"ok": True, "terminal": True,
            "status": "WorkflowExecutionStatus.FAILED"})
        self.assertEqual(p["new_status"], "failed")

    def test_temporal_waiting_or_blocked_never_looks_completed(self):
        for outcome in ("waiting_for_binding", "blocked", None):
            with self.subTest(outcome=outcome):
                self.assertIsNone(self.check({"ok": True, "terminal": True,
                    "status": "WorkflowExecutionStatus.COMPLETED",
                    "result_status": outcome}))


if __name__ == "__main__":
    unittest.main()
