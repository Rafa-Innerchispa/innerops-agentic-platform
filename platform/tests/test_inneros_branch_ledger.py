"""Offline regression tests for branch preservation and truthful release flags."""
import importlib.util
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[2] / "scripts" / "inneros_branch_ledger.py"
SPEC = importlib.util.spec_from_file_location("inneros_branch_ledger_under_test", FILE)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class InnerOSBranchLedgerTests(unittest.TestCase):
    def test_unmerged_commits_are_not_considered_safe_to_merge(self):
        candidate = {"name": "fix/valuable", "sha": "a" * 40, "ahead": 5, "behind": 50, "prs": []}
        self.assertEqual(mod.classification(candidate), "REVISAR_SIN_PR")
        candidate["prs"] = [119]
        self.assertEqual(mod.classification(candidate), "PR_ABIERTO")
        candidate["bulk_risk"] = True
        self.assertEqual(mod.classification(candidate), "RIESGO_ALTO")
        candidate["error"] = "API unavailable"
        self.assertEqual(mod.classification(candidate), "ERROR")

    def test_branch_in_main_history_is_not_marked_as_missing(self):
        self.assertEqual(mod.classification({"ahead": 0, "prs": [], "behind": 6}), "EN_HISTORIA_MAIN")


    def test_separate_legacy_root_is_not_a_transport_error_or_safe_merge(self):
        branch = {"name": "chatgpt/innerops-bootstrap", "sha": "f" * 40,
                  "prs": [], "no_common_ancestor": True}
        self.assertEqual(mod.classification(branch), "HISTORIA_SEPARADA")
        self.assertNotEqual(mod.classification(branch), "EN_HISTORIA_MAIN")

    def test_compare_404_no_common_ancestor_is_distinct_from_api_failures(self):
        github_error = HTTPError(
            "https://api.github.com/repos/test/repo/compare/main...branch",
            404, "Not Found", {},
            BytesIO(b'{"message":"No common ancestor between main and branch."}'))
        with patch.dict(mod.os.environ, {"GITHUB_TOKEN": "test-token"}):
            with patch.object(mod, "urlopen", side_effect=github_error):
                with self.assertRaisesRegex(RuntimeError, "no_common_ancestor"):
                    mod.request("test/repo", "compare/main...branch")

    def test_ledger_has_no_direct_main_publish_function(self):
        self.assertFalse(hasattr(mod, "publish"))

    def test_dangerous_bulk_deletion_is_flagged(self):
        result = mod.summarize_compare({"ahead_by": 43, "behind_by": 337,
            "files": [{"filename": "backups/deleted.py", "deletions": 216026, "additions": 0}]})
        self.assertEqual(result["ahead"], 43)
        self.assertTrue(result["bulk_risk"])

    def test_without_runtime_attestation_production_is_unknown(self):
        result = mod.production_status("a" * 40, {
            "hosts": {"amd": {"verified": False, "runtime_git_sha": "a" * 40},
                      "intel": {"verified": False}}})
        self.assertEqual([r["status"] for r in result], ["NO_CERTIFICADO", "NO_CERTIFICADO"])

    def test_attestation_mismatch_is_drift_not_deployed(self):
        result = mod.production_status("a" * 40, {
            "hosts": {"amd": {"verified": True, "runtime_git_sha": "b" * 40,
                              "evidence_path": "var/evidence/amd.json"}}})
        self.assertEqual(result[0]["status"], "DESFASADO")

    def test_report_enumerates_every_branch_including_legacy(self):
        rows = [{"name": "chatgpt/r" + str(i), "sha": "a" * 40,
                 "prs": [], "ahead": 1, "behind": 7, "changed_files": 2,
                 "classification": "REVISAR_SIN_PR"} for i in range(263)]
        report = {"repo": "Rafa-Innerchispa/innerops-agentic-platform",
                  "main_sha": "b" * 40, "generated_at": "2026-10-12T15:00:00Z",
                  "branches_total": 264, "prs": [],
                  "production": mod.production_status("b" * 40, {"hosts": {}}),
                  "rows": rows}
        text = mod.render(report)
        self.assertIn("chatgpt/r0", text)
        self.assertIn("chatgpt/r262", text)
        self.assertEqual(text.count("REVISAR_SIN_PR |"), 263)
        self.assertIn("NO_CERTIFICADO", text)
        self.assertNotIn("rm -rf", text)


if __name__ == "__main__":
    unittest.main()
