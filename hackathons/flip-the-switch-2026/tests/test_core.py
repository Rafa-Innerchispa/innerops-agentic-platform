import unittest
from dataclasses import replace
from inneros_incident_room.core import (
    Incident, Action, HumanApproval, PolicyDenied, enforce, execute_fixture,
    load_incident_dict, propose_actions, receipt_as_dict,
)


class OfflineIncidentTests(unittest.TestCase):
    def setUp(self):
        self.incident = Incident("I-1", "Synthetic Building", "camera unavailable",
                                 "camera-1", "synthetic", "2026-10-22T00:00:00Z")
        self.observe, self.restart = propose_actions(self.incident)

    def test_observation_does_not_need_approval_or_mutate(self):
        state = {"camera-1": "degraded"}
        receipt = execute_fixture(self.observe, self.incident, state)
        self.assertTrue(receipt.independent_verification)
        self.assertEqual(state["camera-1"], "degraded")
        self.assertEqual(receipt.source, "synthetic")

    def test_unapproved_execution_fails_closed(self):
        state = {"camera-1": "degraded"}
        with self.assertRaises(PolicyDenied):
            execute_fixture(self.restart, self.incident, state)
        self.assertEqual(state["camera-1"], "degraded")

    def test_deny_fails_closed(self):
        state = {"camera-1": "degraded"}
        with self.assertRaises(PolicyDenied):
            execute_fixture(self.restart, self.incident, state,
                            HumanApproval(self.restart.action_id, "camera-1", "reviewer", False))
        self.assertEqual(state["camera-1"], "degraded")

    def test_wrong_target_approval_rejected(self):
        with self.assertRaises(PolicyDenied):
            enforce(self.restart, self.incident,
                    HumanApproval(self.restart.action_id, "another-camera", "reviewer", True))

    def test_wrong_action_approval_rejected(self):
        with self.assertRaises(PolicyDenied):
            enforce(self.restart, self.incident,
                    HumanApproval("OTHER", "camera-1", "reviewer", True))

    def test_approved_synthetic_action_has_verifiable_receipt(self):
        state = {"camera-1": "degraded"}
        receipt = execute_fixture(self.restart, self.incident, state,
                                  HumanApproval(self.restart.action_id, "camera-1", "reviewer", True))
        self.assertEqual(state["camera-1"], "healthy")
        self.assertEqual(receipt.outcome, "verified_simulation")
        self.assertEqual(len(receipt.evidence_sha256), 64)
        self.assertEqual(receipt_as_dict(receipt)["source"], "synthetic")

    def test_non_synthetic_source_rejected(self):
        with self.assertRaises(PolicyDenied):
            propose_actions(replace(self.incident, source="live"))

    def test_non_synthetic_scope_rejected(self):
        with self.assertRaises(PolicyDenied):
            enforce(replace(self.observe, scope="production"), self.incident)

    def test_unknown_operation_rejected(self):
        with self.assertRaises(PolicyDenied):
            enforce(replace(self.observe, operation="reboot_switch"), self.incident)

    def test_unknown_incident_target_rejected(self):
        with self.assertRaises(PolicyDenied):
            enforce(replace(self.observe, target_alias="camera-2"), self.incident)

    def test_restart_only_from_degraded(self):
        with self.assertRaises(PolicyDenied):
            execute_fixture(self.restart, self.incident, {"camera-1": "healthy"},
                            HumanApproval(self.restart.action_id, "camera-1", "reviewer", True))

    def test_parses_valid_fixture(self):
        data = vars(self.incident).copy()
        self.assertEqual(load_incident_dict(data), self.incident)


if __name__ == "__main__":
    unittest.main()
