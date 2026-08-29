import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
CARD_PATH = REPO_ROOT / "platform" / "docs" / "evidence" / "hackathon_live_evidence_kpi_card_2026-08-29.json"
README_PATH = REPO_ROOT / "docs" / "HACKATHON_LIVE_EVIDENCE_2026-08-29.md"


class HackathonLiveEvidenceCardTests(unittest.TestCase):
    def test_kpi_contract_preserves_truth_boundary(self):
        card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
        kpi = card["kpi"]
        self.assertEqual(kpi["human_baseline_minutes"], 120)
        self.assertEqual(kpi["assisted_minutes"], 10)
        self.assertEqual(kpi["saved_minutes"], 110)
        self.assertEqual(kpi["human_hours_returned"], 1.8333)
        self.assertEqual(kpi["reduction_percent"], 91.67)
        self.assertEqual(kpi["speedup"], 12.0)
        self.assertEqual(kpi["verified_human_hours_returned"], 0.0)
        self.assertEqual(kpi["measurement_state"], "legacy_unclassified_pending_evidence_review")
        self.assertTrue(card["truth_policy"]["unverified_legacy_events_are_not_verified_hhr"])

    def test_judge_claims_have_status_and_evidence_refs(self):
        card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
        claims = card["live_verification"]
        self.assertGreaterEqual(len(claims), 8)
        statuses = {claim["status"] for claim in claims}
        self.assertIn("PASS", statuses)
        self.assertIn("PARTIAL", statuses)
        for claim in claims:
            self.assertIn(claim["status"], {"PASS", "PARTIAL", "FAIL"})
            self.assertTrue(claim["evidence_refs"], claim["claim"])
            self.assertTrue(claim["judge_check"], claim["claim"])
        google = next(claim for claim in claims if "Google mandatory" in claim["claim"])
        self.assertEqual(google["status"], "PARTIAL")

    def test_readme_points_to_contract_and_live_checks(self):
        text = README_PATH.read_text(encoding="utf-8")
        self.assertIn("What Judges Can Verify Live", text)
        self.assertIn("hackathon_live_evidence_kpi_card_2026-08-29.json", text)
        self.assertIn("legacy_unclassified_pending_evidence_review", text)


if __name__ == "__main__":
    unittest.main()
