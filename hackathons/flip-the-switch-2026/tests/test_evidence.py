import unittest
from dataclasses import replace

from inneros_incident_room.core import Incident, HumanApproval, execute_fixture, propose_actions
from inneros_incident_room.evidence import verify_receipt_integrity


class ReusableEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.incident = Incident("S-1", "Mock Site", "Synthetic camera unreachable",
                                 "mock-camera", "synthetic", "2026-10-20T12:00:00Z")
        self.observe, self.restart = propose_actions(self.incident)
        self.approval = HumanApproval(self.restart.action_id, "mock-camera", "tester", True)

    def test_receipt_digest_recomputation_success(self):
        receipt = execute_fixture(self.restart, self.incident, {"mock-camera": "degraded"}, self.approval)
        self.assertTrue(verify_receipt_integrity(receipt))

    def test_receipt_digest_detects_altered_post_state(self):
        receipt = execute_fixture(self.restart, self.incident, {"mock-camera": "degraded"}, self.approval)
        self.assertFalse(verify_receipt_integrity(replace(receipt, post_state="degraded")))

    def test_receipt_digest_detects_altered_approval(self):
        receipt = execute_fixture(self.restart, self.incident, {"mock-camera": "degraded"}, self.approval)
        self.assertFalse(verify_receipt_integrity(replace(receipt, approval="other-person")))

    def test_receipt_digest_rejects_false_source(self):
        receipt = execute_fixture(self.observe, self.incident, {"mock-camera": "degraded"})
        self.assertFalse(verify_receipt_integrity(replace(receipt, source="live")))

    def test_unavailable_readback_never_counts_as_verified(self):
        state = {"mock-camera": "degraded"}
        def broken(_):
            raise RuntimeError("offline observation failure")
        receipt = execute_fixture(self.restart, self.incident, state, self.approval, readback=broken)
        self.assertEqual(state["mock-camera"], "healthy")
        self.assertEqual(receipt.outcome, "unverified")
        self.assertFalse(receipt.independent_verification)
        self.assertTrue(verify_receipt_integrity(receipt))

    def test_stale_readback_never_counts_as_verified(self):
        state = {"mock-camera": "degraded"}
        receipt = execute_fixture(self.restart, self.incident, state, self.approval,
                                  readback=lambda _: "degraded")
        self.assertEqual(receipt.outcome, "unverified")
        self.assertFalse(receipt.independent_verification)

    def test_observation_receipt_integrity(self):
        receipt = execute_fixture(self.observe, self.incident, {"mock-camera": "degraded"})
        self.assertTrue(verify_receipt_integrity(receipt))


if __name__ == "__main__":
    unittest.main()
