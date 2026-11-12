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
        self.assertEqual(self.check(t)["new_status"], "verification")

    def test_verification_task_does_not_require_coding_diff(self):
        self.task["task_class"] = "verification"
        p = self.check({"ok": True, "terminal": True,
            "status": "WorkflowExecutionStatus.COMPLETED", "result_status": "completed"})
        self.assertEqual(p["new_status"], "verification")

    def test_reconcile_never_proposes_terminal_completed(self):
        for task_class in ("coding", "verification", "implementation"):
            task = {**self.task, "task_class": task_class}
            temporal = {
                "ok": True,
                "terminal": True,
                "status": "WorkflowExecutionStatus.COMPLETED",
                "result_status": "completed",
                "result_gate_passed": True,
            }
            prop = reconcile._proposed_action(task, temporal)
            if prop:
                self.assertNotEqual(prop["new_status"], "completed")

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


class ReconcileSupersededTests(unittest.TestCase):
    """Lease-expired claimed task replaced by a newer linked task (Kiro case)."""

    def old_claim(self):
        return {"task_id": "ops_8ce2", "status": "claimed",
                "lease_until": "2020-01-01T00:00:00+00:00",
                "correlation_id": "GB-KIRO-CREW-VERIFY-BOTH-20261111"}

    def new_claim(self, status="claimed"):
        return {"task_id": "ops_345e", "status": status,
                "lease_until": "2099-01-01T00:00:00+00:00",
                "correlation_id": "GB-KIRO-CREW-VERIFY-REISSUE-20261111-02",
                "supersedes_task_id": "ops_8ce2"}

    def test_expired_claim_with_live_superseder_proposes_superseded(self):
        old, new = self.old_claim(), self.new_claim()
        prop = reconcile._proposed_superseded(old, [old, new])
        self.assertIsNotNone(prop)
        self.assertEqual(prop["new_status"], "superseded")
        self.assertIn("ops_345e", prop["reason"])
        self.assertEqual(prop["superseded_by"], "ops_345e")

    def test_no_superseder_link_proposes_nothing(self):
        old = self.old_claim()
        other = {"task_id": "ops_9999", "status": "claimed",
                 "lease_until": "2099-01-01T00:00:00+00:00"}
        self.assertIsNone(reconcile._proposed_superseded(old, [old, other]))

    def test_valid_lease_never_superseded(self):
        old = self.old_claim()
        old["lease_until"] = "2099-01-01T00:00:00+00:00"
        self.assertIsNone(reconcile._proposed_superseded(old, [old, self.new_claim()]))

    def test_terminal_sibling_does_not_supersede(self):
        old = self.old_claim()
        done = self.new_claim(status="completed")
        self.assertIsNone(reconcile._proposed_superseded(old, [old, done]))

    def test_non_claimed_task_never_superseded(self):
        old = self.old_claim()
        old["status"] = "awaiting_antigravity_claim"
        self.assertIsNone(reconcile._proposed_superseded(old, [old, self.new_claim()]))


if __name__ == "__main__":
    unittest.main()
