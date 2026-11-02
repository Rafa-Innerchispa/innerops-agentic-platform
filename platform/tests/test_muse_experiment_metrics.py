"""Offline confidence and measurement tests for InnerOS self-healing experimental telemetry."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from inneros_core_runtime.muse_experiment_metrics import (
    ExperimentJournal, quote_from_response, price_quote, score_case,
)


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = ExperimentJournal(Path(self.tmp.name) / "protected" / "muse-results.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_muse_wonder_pricing_standard(self):
        q = price_quote("muse-wonder-1.0", input_tokens=10000, output_tokens=3000)
        self.assertEqual("0.1", q["estimated_cost_usd"])
        self.assertEqual("LIST_PRICE_ESTIMATE_NOT_META_BILLING", q["cost_truth"])

    def test_spark_first_incomplete_price(self):
        q = price_quote("muse-spark-1.3", input_tokens=108, output_tokens=192)
        self.assertEqual("0.00095100", q["estimated_cost_usd"])

    def test_cached_input_discount(self):
        q = price_quote("muse-wonder-1.0", input_tokens=10000, cached_input_tokens=5000, output_tokens=3000)
        self.assertEqual("0.0810", q["estimated_cost_usd"])

    def test_reasoning_tokens_not_double_billed(self):
        q = quote_from_response("muse-wonder-1.0", {
            "input_tokens": 100, "output_tokens": 200,
            "total_tokens": 300,
            "output_tokens_details": {"reasoning_tokens": 140},
        })
        self.assertEqual(140, q["reasoning_tokens"])
        self.assertEqual(60, q["visible_output_tokens_estimated"])
        self.assertEqual(300, q["total_tokens_reported"])
        self.assertEqual("0.0044", q["estimated_cost_usd"])

    def test_price_refuses_invented_model_cost(self):
        with self.assertRaises(ValueError):
            price_quote("muse-wonder-full-1.0", input_tokens=5, output_tokens=50)

    def test_price_refuses_invalid_tokens_and_cache(self):
        for tokens in (True, -1, 2.5):
            with self.assertRaises(ValueError):
                price_quote("muse-wonder-1.0", input_tokens=tokens, output_tokens=10)
        with self.assertRaises(ValueError):
            price_quote("muse-spark-1.3", input_tokens=2, cached_input_tokens=3, output_tokens=4)
        with self.assertRaises(ValueError):
            price_quote("muse-spark-1.3", input_tokens=3, output_tokens=4, extra_tool_cost_usd="-1")

    def test_private_journal_append_and_chain(self):
        event = self.journal.append("BASELINE_CI", "meta-selfheal-01", {
            "project_id": "inneros-meta-guardian-2026",
            "workflow_run_url": "https://github.com/Rafa-Innerchispa/innerops-agentic-platform/actions/runs/41510104055",
            "tests_passed": 333, "tests_failed": 4,
            "status": "FAILED_CI",
        })
        self.assertEqual("0" * 64, event["previous_hash"])
        self.journal.append("LOCAL_DIAGNOSIS", "meta-selfheal-01", {
            "model": "amd-local-qwen", "status": "DIAGNOSIS_STARTED",
        })
        self.assertEqual(2, len(self.journal.read()))
        self.assertEqual(2, self.journal.verify()["total_events"])
        self.assertTrue(self.journal.verify()["valid"])
        if os.name == "posix":
            self.assertEqual(0o600, self.journal.path.stat().st_mode & 0o777)

    def test_private_journal_rejects_sensitive_or_unknown_fields(self):
        with self.assertRaises(ValueError):
            self.journal.append("META_REQUEST", "meta-selfheal-01", {"api_key": "secret"})
        with self.assertRaises(ValueError):
            self.journal.append("META_REQUEST", "meta-selfheal-01", {"raw_prompt": "private"})
        with self.assertRaises(ValueError):
            self.journal.append("META_REQUEST", "meta-selfheal-01", {"input_tokens": -1})
        self.assertEqual(0, len(self.journal.read()))

    def test_tamper_detected(self):
        self.journal.append("BASELINE_CI", "meta-selfheal-01", {"tests_failed": 4})
        with sqlite3.connect(self.journal.path) as con:
            con.execute("UPDATE events SET data_json=? WHERE seq=1", ('{"tests_failed":0}',))
        result = self.journal.verify()
        self.assertFalse(result["valid"])
        self.assertEqual(1, result["failed_seq"])

    def test_cross_process_reopen_chain(self):
        self.journal.append("BASELINE_CI", "meta-selfheal-01", {"tests_failed": 4})
        again = ExperimentJournal(self.journal.path)
        again.append("HUMAN_REVIEW", "meta-selfheal-01", {"status": "PENDING"})
        self.assertTrue(self.journal.verify()["valid"])
        self.assertEqual(2, len(self.journal.read()))

    def test_no_heal_claim_with_only_model_statement(self):
        self.journal.append("BASELINE_CI", "case1", {
            "workflow_run_url": "https://github.com/example/run/1", "tests_failed": 4,
        })
        self.journal.append("META_RESPONSE", "case1", {
            "status": "REAL_SUCCESS", "model": "muse-wonder-1.0",
        })
        result = score_case(self.journal.read("case1"))
        self.assertFalse(result["claim_self_healed"])
        self.assertEqual("REAL_SUCCESS", result["meta_result"])

    def test_no_heal_claim_when_ci_still_failed(self):
        self.journal.append("BASELINE_CI", "case1", {
            "workflow_run_url": "https://github.com/example/run/1", "tests_failed": 4,
        })
        self.journal.append("AFTER_CI", "case1", {
            "workflow_run_url": "https://github.com/example/run/2", "tests_failed": 2,
        })
        result = score_case(self.journal.read("case1"))
        self.assertEqual(2, result["failed_tests_delta"])
        self.assertFalse(result["claim_self_healed"])

    def test_event_has_no_automatic_network_requests(self):
        self.journal.append("EXPERIMENT_BLOCKED", "case1", {
            "status": "WAITING_OWNER_GRANT", "model": "muse-wonder-1.0",
        })
        self.assertEqual(1, len(self.journal.read("case1")))


if __name__ == "__main__":
    unittest.main()
