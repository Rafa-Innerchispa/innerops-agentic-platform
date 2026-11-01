"""Security and reuse tests for the permanent InnerOS Meta provider.

No real key, network or Mongo database is required. pytest is not required.
Run: PYTHONPATH=platform python -m unittest platform.tests.test_meta_model_provider -v
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from inneros_core_runtime import meta_model_provider as meta

PROMPT = "FICTIONAL LAB DATA ONLY: simulated ethernet heartbeat missed once; no physical fault verified."


class Response:
    status = 200
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n=-1):
        return self.payload[:n]


class MetaProviderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "protected" / "grants.sqlite"
        self.ledger = meta.MetaGrantLedger(self.path)
        self.project = "inneros-meta-guardian-2026"
        self.out_cap = 96

    def tearDown(self):
        self.temp.cleanup()

    def _approval(self, project=None, prompt=PROMPT, cap=None):
        return {
            "project_id": project or self.project, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "model": meta.MODEL, "max_output_tokens": cap or self.out_cap,
            "approval_ref": "ha_owner_approval_test_only",
        }

    def _issue(self, project=None, prompt=PROMPT, cap=None):
        return self.ledger.issue(
            project_id=project or self.project, prompt=prompt,
            approval=self._approval(project, prompt, cap),
            verifier=lambda approved: approved["approval_ref"] == "ha_owner_approval_test_only",
            max_output_tokens=cap or self.out_cap,
        )

    def _response(self):
        return {"id": "resp_live_mock_verified", "model": meta.MODEL, "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "Lab: investigate the monitor, no device action."}]}],
                "usage": {"input_tokens": 44, "output_tokens": 21, "total_tokens": 65}}

    def test_provider_manifest_is_generic_and_no_key(self):
        document = meta.manifest_document()
        self.assertEqual("meta-model-api", document["id"])
        self.assertIn("frontier_reasoning", document["capabilities"])
        self.assertEqual("owner_vault", document["auth_mode"])
        self.assertEqual("explicit_burst_only", meta.model_provider_document()["cost_policy"])
        self.assertEqual("owner_vault:model_api_provider/meta_model_api_key", meta.CREDENTIAL_REF)

    def test_vault_not_loaded_by_description_or_manifest(self):
        self.assertNotIn("MODEL_API_KEY", json.dumps(meta.manifest_document()))
        doc = meta.model_provider_document()
        self.assertEqual(90, doc["priority"])
        self.assertEqual(["frontier_reasoning", "specialized_external_reasoning"], doc["task_classes"])

    def test_no_grant_without_actual_validator(self):
        with self.assertRaises(PermissionError):
            self.ledger.issue(project_id=self.project, prompt=PROMPT, approval=self._approval(), verifier=None)
        with self.assertRaises(PermissionError):
            self.ledger.issue(project_id=self.project, prompt=PROMPT, approval=self._approval(), verifier=lambda a: False)

    def test_grant_is_bound_to_project_prompt_and_model_budget(self):
        approval = self._approval()
        with self.assertRaises(PermissionError):
            self.ledger.issue(project_id="other_project", prompt=PROMPT, approval=approval, verifier=lambda _: True)
        with self.assertRaises(PermissionError):
            self.ledger.issue(project_id=self.project, prompt=PROMPT+"modified", approval=approval, verifier=lambda _: True)
        with self.assertRaises(PermissionError):
            self.ledger.issue(project_id=self.project, prompt=PROMPT, approval=approval, verifier=lambda _: True,
                              max_output_tokens=95)

    def test_reject_non_synthetic_data(self):
        with self.assertRaises(PermissionError):
            self.ledger.issue(project_id=self.project, prompt="Company secret", approval=self._approval(), verifier=lambda _: True)
        with self.assertRaises(PermissionError):
            self.ledger.issue(project_id=self.project, prompt=PROMPT, classification="PRIVATE_CUSTOMER",
                              approval=self._approval(), verifier=lambda _: True)

    def test_reject_large_budget(self):
        with self.assertRaises(ValueError):
            self.ledger.issue(project_id=self.project, prompt=PROMPT, approval=self._approval(), verifier=lambda _: True,
                              max_output_tokens=1024)

    def test_cross_process_ledger_once_and_no_secret(self):
        grant = self._issue()
        reopened = meta.MetaGrantLedger(self.path)
        calls = []
        def call(req, timeout):
            calls.append(req)
            self.assertEqual("POST", req.get_method())
            self.assertEqual(meta.RESPONSES_URL, req.full_url)
            doc = json.loads(req.data)
            self.assertEqual(False, doc["store"])
            self.assertEqual(self.out_cap, doc["max_output_tokens"])
            return Response(self._response())
        result = meta.invoke_with_grant(
            ledger=reopened, grant_id=grant["grant_id"], project_id=self.project, prompt=PROMPT,
            credential_loader=lambda: "fake_api_key_never_saved", transport=call,
        )
        self.assertEqual("REAL_SUCCESS", result["status"])
        self.assertEqual("resp_live_mock_verified", result["provider_response_id"])
        self.assertEqual(65, result["usage"]["total_tokens"])
        self.assertTrue(result["response_sha256"])
        self.assertIsNone(result["cost_usd_verified"])
        self.assertEqual(1, len(calls))
        persisted = meta.MetaGrantLedger(self.path).last_receipt(grant["grant_id"])
        self.assertEqual("REAL_SUCCESS", persisted["status"])
        self.assertEqual(65, persisted["usage"]["total_tokens"])
        self.assertNotIn("fake_api_key_never_saved", str(persisted))
        self.assertNotIn(PROMPT, str(persisted))
        if os.name == "posix":
            self.assertEqual(0o600, self.path.stat().st_mode & 0o777)
        with self.assertRaises(PermissionError):
            meta.invoke_with_grant(ledger=self.ledger, grant_id=grant["grant_id"],
                                   project_id=self.project, prompt=PROMPT,
                                   credential_loader=lambda: "key", transport=call)
        self.assertEqual(1, len(calls))

    def test_wrong_project_does_not_consume_correct_grant(self):
        grant = self._issue()
        with self.assertRaises(PermissionError):
            meta.invoke_with_grant(ledger=self.ledger, grant_id=grant["grant_id"],
                                   project_id="other-project", prompt=PROMPT,
                                   credential_loader=lambda: "key", transport=lambda *a, **k: self.fail("called"))
        self.assertIsNone(self.ledger.last_receipt(grant["grant_id"]))

    def test_402_payment_error_consumed_once(self):
        grant = self._issue()
        calls = []
        def call(req, timeout):
            calls.append(1)
            raise HTTPError(req.full_url, 402, "Billing blocked", {},
                            BytesIO(b'{"error":{"code":"billing_not_configured"}}'))
        output = meta.invoke_with_grant(ledger=self.ledger, grant_id=grant["grant_id"],
                                        project_id=self.project, prompt=PROMPT,
                                        credential_loader=lambda: "fake_key", transport=call)
        self.assertEqual("BILLING_BLOCKED", output["status"])
        self.assertEqual(402, output["http_status"])
        self.assertEqual("HTTP_402", output["error_type"])
        self.assertEqual(1, len(calls))
        with self.assertRaises(PermissionError):
            meta.invoke_with_grant(ledger=self.ledger, grant_id=grant["grant_id"],
                                   project_id=self.project, prompt=PROMPT,
                                   credential_loader=lambda: "fake_key", transport=call)
        self.assertEqual(1, len(calls))

    def test_no_valid_provider_id_no_real_success(self):
        grant = self._issue()
        output = meta.invoke_with_grant(
            ledger=self.ledger, grant_id=grant["grant_id"], project_id=self.project, prompt=PROMPT,
            credential_loader=lambda: "fake_key", transport=lambda req, timeout: Response({
                "status": "completed", "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": "Hello"}]}],
            }),
        )
        self.assertEqual("BLOCKED", output["status"])
        self.assertEqual("UNVERIFIED_PROVIDER_RESPONSE", output["error_type"])

    def test_credential_missing_prevents_network(self):
        grant = self._issue()
        receipt = meta.invoke_with_grant(
            ledger=self.ledger, grant_id=grant["grant_id"], project_id=self.project, prompt=PROMPT,
            credential_loader=lambda: "", transport=lambda req, timeout: self.fail("NETWORK CALLED"),
        )
        self.assertEqual("BLOCKED", receipt["status"])
        self.assertEqual("PermissionError", receipt["error_type"])
        self.assertIsNotNone(self.ledger.last_receipt(grant["grant_id"]))

    def test_two_projects_have_separate_grants_and_receipts(self):
        a = self._issue()
        b = self._issue(project="physical-guardian")
        self.assertNotEqual(a["grant_id"], b["grant_id"])
        self.assertEqual("physical-guardian", b["project_id"])
        self.assertIsNone(self.ledger.last_receipt(a["grant_id"]))
        self.assertIsNone(self.ledger.last_receipt(b["grant_id"]))


if __name__ == "__main__":
    unittest.main()
