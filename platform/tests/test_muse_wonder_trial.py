"""Offline simulated transport tests; no Meta key and no network traffic."""
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from io import BytesIO

from inneros_core_runtime import muse_wonder_trial as t


class FakeResponse:
    def __init__(self, obj, status=200):
        self.status = status
        self.headers = {"x-request-id": "synthetic_meta_http_req"}
        self.payload = json.dumps(obj).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n):
        return self.payload[:n]


class MuseWonderTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "private"
        self.attempts = []

    def tearDown(self):
        self.tmp.cleanup()

    def _transport(self, req, timeout):
        self.attempts.append(req)
        self.assertEqual("POST", req.get_method())
        self.assertEqual(t.URL, req.full_url)
        body = json.loads(req.data)
        self.assertEqual(t.MODEL, body["model"])
        self.assertFalse(body["store"])
        self.assertEqual(4096, body["max_output_tokens"])
        self.assertIn("FICTIONAL LAB DATA ONLY", body["input"])
        return FakeResponse({
            "id": "resp_wonder_fixture_only", "model": t.MODEL, "status": "completed",
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "F1: stale expectation possible; reproduce safely."}]}],
            "usage": {"input_tokens": 310, "output_tokens": 60, "total_tokens": 370,
                      "output_tokens_details": {"reasoning_tokens": 20}},
        })

    def _run(self, trial_id="wonder_trial_one", transport=None, **kwargs):
        return t.run_trial(
            trial_id=trial_id, record_dir=self.root,
            authorized=True, approval_ref="owner-operator-lab-test-only",
            credential_loader=lambda: "mock_key_not_real",
            transport=transport or self._transport,
            **kwargs,
        )

    def test_single_synthetic_wonder_has_receipt_and_quote(self):
        r = self._run()
        self.assertEqual("REAL_SUCCESS", r["result"])
        self.assertEqual(t.MODEL, r["model_requested"])
        self.assertEqual(370, r["usage"]["total_tokens"])
        self.assertEqual("resp_wonder_fixture_only", r["provider_response_id"])
        self.assertEqual(1, len(self.attempts))
        self.assertTrue((self.root/"wonder_trial_one"/"claim.json").exists())
        self.assertTrue((self.root/"wonder_trial_one"/"provider_response.json").exists())
        self.assertTrue((self.root/"wonder_trial_one"/"receipt.json").exists())
        self.assertNotIn("mock_key_not_real", (self.root/"wonder_trial_one"/"receipt.json").read_text())
        self.assertIsNone(r["verified_billing_usd"])
        self.assertTrue((self.root/"muse_experiments.sqlite3").exists())

    def test_duplicate_trial_id_never_calls_network_twice(self):
        self._run()
        with self.assertRaises(FileExistsError):
            self._run()
        self.assertEqual(1, len(self.attempts))

    def test_no_approval_blocks_before_network_and_write(self):
        with self.assertRaises(PermissionError):
            t.run_trial(
                trial_id="wonder_trial_none", record_dir=self.root,
                authorized=False, approval_ref="",
                credential_loader=lambda: "mock", transport=self._transport,
            )
        self.assertFalse(self.root.exists())
        self.assertEqual(0, len(self.attempts))

    def test_budget_preflight_blocks_large_quote(self):
        with self.assertRaises(ValueError):
            self._run(budget_usd="0.001")
        self.assertFalse(self.root.exists())
        self.assertEqual(0, len(self.attempts))

    def test_restrict_output_cap_and_effort(self):
        for n in (1, 1000, 8193):
            with self.assertRaises(ValueError):
                self._run(max_output_tokens=n)
        with self.assertRaises(ValueError):
            self._run(reasoning_effort="max")
        self.assertEqual(0, len(self.attempts))

    def test_refuses_billing_402_and_consumes_id(self):
        def billing(req, timeout):
            self.attempts.append(req)
            raise HTTPError(req.full_url, 402, "Billing required", {},
                BytesIO(b'{"error":{"code":"billing_not_configured"}}'))
        r = self._run(trial_id="wonder_bill", transport=billing)
        self.assertEqual("BILLING_BLOCKED", r["result"])
        self.assertEqual(402, r["http_status"])
        self.assertEqual(1, len(self.attempts))
        with self.assertRaises(FileExistsError):
            self._run(trial_id="wonder_bill", transport=billing)
        self.assertEqual(1, len(self.attempts))

    def test_does_not_call_another_model_or_real_customer(self):
        self._run()
        raw = self.attempts[0].data.decode()
        self.assertNotIn("bellini", raw.lower())
        self.assertNotIn("guardian.creatorcore.ai", raw)
        self.assertNotIn("api_key", raw)
        self.assertNotIn("access_token", raw)
        self.assertNotIn("muse-spark-1.3", raw)

    def test_response_with_no_model_text_not_verified(self):
        def missing(req, timeout):
            self.attempts.append(req)
            return FakeResponse({"id": "resp_no_text", "model": t.MODEL, "status": "completed", "output": [],
                "usage": {"input_tokens": 13, "output_tokens": 100, "total_tokens": 113}})
        r = self._run(trial_id="wonder_empty", transport=missing)
        self.assertEqual("UNVERIFIED_RESPONSE", r["result"])
        self.assertEqual(0, r["visible_text_bytes"])

    def test_one_persisted_hash_chain_event(self):
        self._run()
        from inneros_core_runtime.muse_experiment_metrics import ExperimentJournal
        j = ExperimentJournal(self.root/"muse_experiments.sqlite3")
        self.assertTrue(j.verify()["valid"])
        ev = j.read(t.CASE)
        self.assertEqual(1, len(ev))
        self.assertEqual(t.MODEL, ev[0]["metrics"]["model"])


if __name__ == "__main__":
    unittest.main()
