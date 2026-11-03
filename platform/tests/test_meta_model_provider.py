import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from inneros_core_runtime import meta_model_provider as meta

PROMPT = "FICTIONAL LAB DATA ONLY: uplink status test; report only safe observations"


class Response:
    def __init__(self, data: dict, status: int = 200):
        self.status = status
        self._payload = json.dumps(data).encode("utf-8")

    def read(self, n=None):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


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
            "project_id": project or self.project,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "model": meta.MODEL,
            "max_output_tokens": cap or self.out_cap,
            "owner_actor": "RAFAEL",
            "approval_ref": "ha_owner_approval_test_only_" + (project or self.project),
        }

    def _issue(self, project=None, prompt=PROMPT, cap=None, effort=None):
        return self.ledger.issue(
            project_id=project or self.project,
            prompt=prompt,
            approval=self._approval(project, prompt, cap),
            verifier=lambda approved: approved["approval_ref"].startswith("ha_owner_approval_test_only_"),
            max_output_tokens=cap or self.out_cap,
            reasoning_effort=effort,
        )

    def _response(self):
        return {
            "id": "resp_live_mock_verified",
            "model": meta.MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Lab: investigate the monitor, no device action.",
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 44, "output_tokens": 21, "total_tokens": 65},
        }

    def test_provider_manifest_is_generic_and_no_key(self):
        document = meta.manifest_document()
        self.assertEqual("meta-model-api", document["id"])
        self.assertIn("frontier_reasoning", document["capabilities"])
        self.assertEqual("owner_vault", document["auth_mode"])
        self.assertEqual("explicit_burst_only", meta.model_provider_document()["cost_policy"])
        self.assertEqual("owner_vault:model_api_provider/meta_model_api_key", meta.CREDENTIAL_REF)

    def test_vault_not_loaded_by_description_or_manifest(self):
        self.assertNotIn("MODEL_API_KEY", json.dumps(meta.manifest_document()))

    def test_no_grant_without_actual_validator(self):
        with self.assertRaises(PermissionError):
            self.ledger.issue(
                project_id=self.project,
                prompt=PROMPT,
                approval=self._approval(),
                verifier=None,
            )

    def test_grant_is_bound_to_project_prompt_and_model_budget(self):
        grant = self._issue()
        self.assertTrue(grant["grant_id"].startswith("meta_grant_"))
        self.assertEqual(meta.MODEL, grant["model"])
        self.assertEqual(self.project, grant["project_id"])
        self.assertEqual(meta._sha(PROMPT.encode("utf-8")), grant["prompt_sha256"])

    def test_reject_non_synthetic_data(self):
        with self.assertRaises(PermissionError):
            self.ledger.issue(
                project_id=self.project,
                prompt=PROMPT,
                classification="PRIVATE_CUSTOMER",
                approval=self._approval(),
                verifier=lambda _: True,
            )

    def test_reject_large_budget(self):
        # Exceeding MAX_ALLOWED_OUTPUT_TOKENS (4096) must raise ValueError
        with self.assertRaises(ValueError):
            self.ledger.issue(
                project_id=self.project,
                prompt=PROMPT,
                approval=self._approval(cap=8192),
                verifier=lambda _: True,
                max_output_tokens=8192,
            )

    def test_accept_reasoning_1024_tokens(self):
        # Authorized reasoning budget up to 1024 tokens is permitted
        grant = self._issue(cap=1024, effort="medium")
        self.assertEqual(1024, grant["max_output_tokens"])
        self.assertEqual("medium", grant.get("reasoning_effort"))

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
            ledger=reopened,
            grant_id=grant["grant_id"],
            project_id=self.project,
            prompt=PROMPT,
            credential_loader=lambda: "dummy_vault_secret",
            transport=call,
        )
        self.assertEqual("REAL_SUCCESS", result["status"])
        self.assertEqual(1, len(calls))

        # Replay attempt fails closed without touching network
        with self.assertRaises(PermissionError):
            meta.invoke_with_grant(
                ledger=reopened,
                grant_id=grant["grant_id"],
                project_id=self.project,
                prompt=PROMPT,
                credential_loader=lambda: "dummy_vault_secret",
                transport=call,
            )
        self.assertEqual(1, len(calls))

    def test_signed_owner_approval_cannot_mint_two_paid_grants(self):
        self._issue()
        with self.assertRaisesRegex(PermissionError, "already exchanged"):
            self._issue()

    def test_same_approval_cannot_be_reused_for_another_project(self):
        self._issue()
        # Approval reference must be globally unique within the ledger.
        with self.assertRaisesRegex(PermissionError, "already exchanged"):
            self.ledger.issue(
                project_id="other-project",
                prompt=PROMPT,
                approval={
                    "project_id": "other-project",
                    "prompt_sha256": meta._sha(PROMPT.encode()),
                    "model": meta.MODEL,
                    "max_output_tokens": self.out_cap,
                    "owner_actor": "RAFAEL",
                    "approval_ref": "ha_owner_approval_test_only_" + self.project,
                },
                verifier=lambda _: True,
                max_output_tokens=self.out_cap,
            )

    def test_wrong_project_does_not_consume_correct_grant(self):
        grant = self._issue()
        with self.assertRaises(PermissionError):
            meta.invoke_with_grant(
                ledger=self.ledger,
                grant_id=grant["grant_id"],
                project_id="other-project",
                prompt=PROMPT,
                credential_loader=lambda: "key",
                transport=lambda *a, **k: self.fail("called"),
            )
        self.assertIsNone(self.ledger.last_receipt(grant["grant_id"]))

    def test_402_payment_error_consumed_once(self):
        grant = self._issue()
        calls = []

        def call(req, timeout):
            calls.append(1)
            raise HTTPError(
                req.full_url,
                402,
                "Billing blocked",
                {},
                BytesIO(b'{"error":{"code":"billing_not_configured"}}'),
            )

        output = meta.invoke_with_grant(
            ledger=self.ledger,
            grant_id=grant["grant_id"],
            project_id=self.project,
            prompt=PROMPT,
            credential_loader=lambda: "fake_key",
            transport=call,
        )
        self.assertEqual("BILLING_BLOCKED", output["status"])
        self.assertEqual(402, output["http_status"])
        self.assertEqual("HTTP_402", output["error_type"])
        self.assertEqual(1, len(calls))
        with self.assertRaises(PermissionError):
            meta.invoke_with_grant(
                ledger=self.ledger,
                grant_id=grant["grant_id"],
                project_id=self.project,
                prompt=PROMPT,
                credential_loader=lambda: "fake_key",
                transport=call,
            )
        self.assertEqual(1, len(calls))

    def test_no_valid_provider_id_no_real_success(self):
        grant = self._issue()
        output = meta.invoke_with_grant(
            ledger=self.ledger,
            grant_id=grant["grant_id"],
            project_id=self.project,
            prompt=PROMPT,
            credential_loader=lambda: "fake_key",
            transport=lambda req, timeout: Response({
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hello"}]}],
            }),
        )
        self.assertEqual("BLOCKED", output["status"])
        self.assertEqual("UNVERIFIED_PROVIDER_RESPONSE", output["error_type"])

    def test_credential_missing_prevents_network(self):
        grant = self._issue()
        receipt = meta.invoke_with_grant(
            ledger=self.ledger,
            grant_id=grant["grant_id"],
            project_id=self.project,
            prompt=PROMPT,
            credential_loader=lambda: "",
            transport=lambda req, timeout: self.fail("NETWORK CALLED"),
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

    def test_shared_resource_fabric_registers_meta_once(self):
        fabric_file = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "resource_fabric.py"
        code = fabric_file.read_text(encoding="utf-8")
        self.assertEqual(1, code.count("meta_model_provider.resource_provider_document()"))
        self.assertEqual(1, code.count("meta_model_provider.model_provider_document()"))
        self.assertIn("from raphiia_openai import meta_model_provider", code)

    def test_vault_discovery_is_fail_closed_when_unavailable(self):
        with patch("builtins.__import__", side_effect=RuntimeError("test DB is unavailable")):
            self.assertFalse(meta._has_vault_key())

    def test_ha_owner_approval_verifier(self):
        secret = "test_ha_secret_key_123"
        os.environ["INNEROS_HA_COMPANION_RECEIPT_SECRET"] = secret
        try:
            prompt_sha = meta._sha(PROMPT.encode("utf-8"))
            ref = "task_ha_test_001"
            # V2 approval binds model, exact context and an explicit short expiry.
            expires_epoch = int(time.time()) + 180
            payload = f"{ref}|{self.project}|{meta.MODEL}|{prompt_sha}|{self.out_cap}|{expires_epoch}"
            sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
            valid_scope = {
                "approval_ref": ref,
                "project_id": self.project,
                "prompt_sha256": prompt_sha,
                "model": meta.MODEL,
                "max_output_tokens": self.out_cap,
                "owner_actor": "RAFAEL",
                "expires_epoch": expires_epoch,
                "signature": sig,
            }
            self.assertTrue(meta.verify_ha_owner_approval(valid_scope))
            offline_db = MagicMock()
            offline_db.get_db.side_effect = RuntimeError("no DB")

            # Old signatures were not tied to model or expiry. Reject even if
            # the caller appends a future expiry value after the fact.
            legacy_payload = f"{ref}|{self.project}|{prompt_sha}|{self.out_cap}"
            legacy_sig = hmac.new(secret.encode(), legacy_payload.encode(), hashlib.sha256).hexdigest()
            with patch.dict("sys.modules", {"raphiia_openai.mongo_store": offline_db}):
                self.assertFalse(meta.verify_ha_owner_approval(dict(valid_scope, signature=legacy_sig)))

            # A Companion receipt proves only a task action, not the exact
            # project/model/prompt/budget. It cannot replace the scoped proof.
            task_receipt = {"task_id": ref, "grant_id": "g1", "at": "2026-11-02T00:00:00Z"}
            task_sig_payload = f"{ref}|g1|2026-11-02T00:00:00Z"
            task_receipt["signature"] = hmac.new(
                secret.encode(), task_sig_payload.encode(), hashlib.sha256
            ).hexdigest()
            with patch.dict("sys.modules", {"raphiia_openai.mongo_store": offline_db}):
                self.assertFalse(meta.verify_ha_owner_approval(dict(valid_scope, signature="", companion_receipt=task_receipt)))

            # Non-RAFAEL actor rejected (Section 3.1)
            bad_actor = dict(valid_scope, owner_actor="HACKER")
            self.assertFalse(meta.verify_ha_owner_approval(bad_actor))

            # Missing owner_actor rejected (Section 3.1: never assume default)
            no_actor = dict(valid_scope)
            del no_actor["owner_actor"]
            self.assertFalse(meta.verify_ha_owner_approval(no_actor))

            # Modified prompt sha rejected
            bad_prompt = dict(valid_scope, prompt_sha256="0" * 64)
            self.assertFalse(meta.verify_ha_owner_approval(bad_prompt))

            # Excessive token budget over ceiling rejected
            bad_tokens = dict(valid_scope, max_output_tokens=4096)
            self.assertFalse(meta.verify_ha_owner_approval(bad_tokens))

            # Unsigned scope without DB grant fails closed
            unsigned = dict(valid_scope, signature="")
            self.assertFalse(meta.verify_ha_owner_approval(unsigned))
        finally:
            os.environ.pop("INNEROS_HA_COMPANION_RECEIPT_SECRET", None)

    def test_ha_owner_approval_expired_fails_closed(self):
        # Section 3.3: Expiry validation
        secret = "test_ha_secret_key_123"
        os.environ["INNEROS_HA_COMPANION_RECEIPT_SECRET"] = secret
        try:
            prompt_sha = meta._sha(PROMPT.encode("utf-8"))
            ref = "task_ha_test_exp"
            exp_past = time.time() - 60  # expired 1 minute ago
            payload = f"{ref}|{self.project}|{meta.MODEL}|{prompt_sha}|{self.out_cap}|{exp_past}"
            sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
            expired_scope = {
                "approval_ref": ref,
                "project_id": self.project,
                "prompt_sha256": prompt_sha,
                "model": meta.MODEL,
                "max_output_tokens": self.out_cap,
                "owner_actor": "RAFAEL",
                "expires_epoch": exp_past,
                "signature": sig,
            }
            self.assertFalse(meta.verify_ha_owner_approval(expired_scope))
        finally:
            os.environ.pop("INNEROS_HA_COMPANION_RECEIPT_SECRET", None)

    def test_ha_owner_approval_mongo_query_or(self):
        # Section 3.2: MongoDB query uses $or and matches active/authorized status
        mock_store = MagicMock()
        mock_db = MagicMock()
        mock_grants = MagicMock()
        mock_db.__getitem__.return_value = mock_grants
        mock_store.get_db.return_value = mock_db

        prompt_sha = meta._sha(PROMPT.encode("utf-8"))
        ref = "task_mongo_001"
        valid_doc = {
            "grant_id": ref,
            "task_id": ref,
            "owner_actor": "RAFAEL",
            "status": "active",
            "token_limit": 512,
            "provider": "meta-model-api",
            "project_id": self.project,
            "prompt_sha256": prompt_sha,
            "model": meta.MODEL,
            "expires_at": datetime.fromtimestamp(time.time() + 180, timezone.utc).isoformat(),
        }
        mock_grants.find_one.return_value = valid_doc

        mock_pkg = MagicMock()
        mock_pkg.mongo_store = mock_store
        with patch.dict("sys.modules", {"raphiia_openai": mock_pkg, "raphiia_openai.mongo_store": mock_store}):
            scope = {
                "approval_ref": ref,
                "project_id": self.project,
                "prompt_sha256": prompt_sha,
                "model": meta.MODEL,
                "max_output_tokens": self.out_cap,
                "owner_actor": "RAFAEL",
                "expires_epoch": time.time() + 120,
            }
            res = meta.verify_ha_owner_approval(scope)
            self.assertTrue(res)

            # Verify query used $or
            call_query = mock_grants.find_one.call_args[0][0]
            self.assertIn("$or", call_query)
            self.assertNotIn("", call_query)
            self.assertEqual([{"grant_id": ref}, {"task_id": ref}], call_query["$or"])

    def test_concurrent_grant_consumption_exactly_once(self):
        # Section 3.4: Replay and concurrency prevention
        grant = self._issue()
        gid = grant["grant_id"]
        results = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            try:
                info = self.ledger._consume(gid, self.project, PROMPT)
                results.append(("OK", info))
            except PermissionError as e:
                results.append(("REJECTED", str(e)))

        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(worker)
            f2 = ex.submit(worker)
            f1.result()
            f2.result()

        statuses = [r[0] for r in results]
        self.assertEqual(1, statuses.count("OK"))
        self.assertEqual(1, statuses.count("REJECTED"))

    def test_incomplete_model_response_distinct_from_success(self):
        # Section 4: incomplete model response is stored as INCOMPLETE_MODEL_RESPONSE
        grant = self._issue()
        incomplete_resp = {
            "id": "resp_trial_incomplete_123",
            "model": meta.MODEL,
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [
                {
                    "type": "reasoning",
                    "status": "incomplete",
                    "id": "rs_123",
                }
            ],
            "usage": {
                "input_tokens": 108,
                "output_tokens": 192,
                "total_tokens": 300,
                "output_tokens_details": {"reasoning_tokens": 190},
            },
        }

        output = meta.invoke_with_grant(
            ledger=self.ledger,
            grant_id=grant["grant_id"],
            project_id=self.project,
            prompt=PROMPT,
            credential_loader=lambda: "key",
            transport=lambda req, timeout: Response(incomplete_resp),
        )

        self.assertEqual("INCOMPLETE_MODEL_RESPONSE", output["status"])
        self.assertEqual("max_output_tokens", output["error_type"])
        self.assertEqual("resp_trial_incomplete_123", output["provider_response_id"])
        self.assertIsNone(output["output_text"])

    def test_reconcile_receipt_and_query_usage(self):
        # Section 5: Reconciling verified probe receipt into the central ledger
        sample_trial_receipt = {
            "probe_id": "meta-no-card-20261101",
            "provider_response_id": "resp_6ae763441da65bb847084f88",
            "http_status": 200,
            "model_requested": "muse-spark-1.3",
            "model_returned": "muse-spark-1.3",
            "provider_completion_status": "incomplete",
            "reason": "MISSING_PROVIDER_ID_COMPLETION_OR_TEXT",
            "request_latency_ms": 3273.322,
            "request_sha256": "ef01a9f81e8d3fd71d3dfdddb3da85de592691384c10389cd27dc06b39dc1142",
            "response_sha256": "c096408b1635262c05c434c706bc01a43488a12b0dae7d4fa7c2af709ab8093e",
            "timestamp_completed": "2026-11-01T16:05:24.454+00:00",
            "usage": {"input_tokens": 108, "output_tokens": 192, "total_tokens": 300},
        }

        rec = self.ledger.reconcile_receipt(sample_trial_receipt, project_id=self.project)
        self.assertTrue(rec["ok"])
        self.assertTrue(rec["reconciled"])

        usage = self.ledger.query_usage(project_id=self.project)
        self.assertEqual(1, usage["count"])
        self.assertEqual(300, usage["total_tokens"])
        self.assertIn("INCOMPLETE_MODEL_RESPONSE", usage["status_breakdown"])
        self.assertIn("2026-11-01", usage["daily_usage"])
        self.assertIn("2026-11", usage["monthly_usage"])
        self.assertIn("amd_local_primary", usage["comparison_vs_local"]["providers"])

    def test_query_usage_and_project_breakdown(self):
        grant_a = self._issue(project="project-alpha")
        grant_b = self._issue(project="project-beta")

        meta.invoke_with_grant(
            ledger=self.ledger,
            grant_id=grant_a["grant_id"],
            project_id="project-alpha",
            prompt=PROMPT,
            credential_loader=lambda: "fake_key",
            transport=lambda req, timeout: Response(self._response()),
        )
        meta.invoke_with_grant(
            ledger=self.ledger,
            grant_id=grant_b["grant_id"],
            project_id="project-beta",
            prompt=PROMPT,
            credential_loader=lambda: "fake_key",
            transport=lambda req, timeout: Response(self._response()),
        )

        all_usage = self.ledger.query_usage()
        self.assertEqual(2, all_usage["count"])
        self.assertEqual(130, all_usage["total_tokens"])

        alpha_usage = self.ledger.query_usage(project_id="project-alpha")
        self.assertEqual(1, alpha_usage["count"])
        self.assertEqual(65, alpha_usage["total_tokens"])
        self.assertEqual("project-alpha", alpha_usage["project_id"])

    def test_provider_comparison_summary(self):
        summary = meta.get_provider_comparison_summary()
        self.assertTrue(summary["ok"])
        self.assertIn("amd_local_primary", summary["providers"])
        self.assertIn("intel_local_standby", summary["providers"])
        self.assertIn("meta_model_api", summary["providers"])
        self.assertEqual("amd_local_primary", summary["default_routing"])
        self.assertEqual(150.0, summary["providers"]["meta_model_api"]["promotional_balance_usd"])

    def test_public_meta_gateway_rejects_untrusted_receipt_import(self):
        from inneros_core_runtime import capability_gateway_model as cgm
        # Receipt provenance must not be a caller-controlled JSON field.
        with patch.object(meta, "MetaGrantLedger", side_effect=AssertionError("no ledger needed")):
            result = cgm._frontier_reason_handler({
                "action": "reconcile_receipt",
                "receipt_data": {"result": "REAL_SUCCESS", "provider_response_id": "forged"},
            }, {})
        self.assertFalse(result["ok"])
        self.assertEqual("trusted_receipt_reconciliation_only", result["error"])

        specs = cgm.get_model_capabilities_specs()
        public_manifest = next(m for m, _ in specs if m["capability_id"] == "model.frontier.reason.v1")
        self.assertNotIn("reconcile_receipt", public_manifest["parameters_schema"]["properties"]["action"]["enum"])

    def test_capability_gateway_meta_discovery_and_invocation(self):
        from inneros_core_runtime import capability_gateway_model as cgm

        health = cgm._provider_query_handler({"action": "provider_health"}, {})
        self.assertTrue(health["ok"])
        self.assertEqual("meta-model-api", health["provider_id"])

        summary = cgm._provider_query_handler({"action": "comparison_summary"}, {})
        self.assertTrue(summary["ok"])
        self.assertIn("amd_local_primary", summary["providers"])
        self.assertIn("meta_model_api", summary["providers"])

        specs = []

        def dummy_register(manifest, handler):
            specs.append((manifest, handler))

        count = cgm.register_model_frontier_capabilities(dummy_register)
        self.assertEqual(2, count)
        cap_ids = [s[0]["capability_id"] for s in specs]
        self.assertIn("model.provider.query.v1", cap_ids)
        self.assertIn("model.frontier.reason.v1", cap_ids)


    def test_wonder_one_shot_grant_is_model_bound_and_cannot_replay(self):
        approved = self._approval()
        approved["model"] = "muse-wonder-1.0"
        grant = self.ledger.issue(
            project_id=self.project, prompt=PROMPT, approval=approved,
            verifier=lambda scope: scope["model"] == "muse-wonder-1.0",
            max_output_tokens=self.out_cap, model="muse-wonder-1.0",
        )
        self.assertEqual("muse-wonder-1.0", grant["model"])
        model = self.ledger._consume(grant["grant_id"], self.project, PROMPT)
        self.assertEqual("muse-wonder-1.0", model["model"])
        with self.assertRaises(PermissionError):
            self.ledger._consume(grant["grant_id"], self.project, PROMPT)
        with self.assertRaises(PermissionError):
            self.ledger.issue(
                project_id=self.project, prompt=PROMPT,
                approval=approved, verifier=lambda _: True,
                max_output_tokens=self.out_cap, model="muse-wonder-1.0",
            )

    def test_wonder_provider_response_enforces_approved_model_without_live_network(self):
        approved = self._approval()
        approved["model"] = "muse-wonder-1.0"
        grant = self.ledger.issue(
            project_id=self.project, prompt=PROMPT, approval=approved,
            verifier=lambda _: True, max_output_tokens=self.out_cap,
            model="muse-wonder-1.0",
        )
        response = self._response()
        response["model"] = "muse-wonder-1.0"
        captured = []
        def fake_transport(req, timeout):
            captured.append(json.loads(req.data.decode("utf-8")))
            return Response(response)
        receipt = meta.invoke_with_grant(
            ledger=self.ledger, grant_id=grant["grant_id"],
            project_id=self.project, prompt=PROMPT,
            credential_loader=lambda: "unit-test-placeholder-not-real-key",
            transport=fake_transport,
        )
        self.assertEqual("REAL_SUCCESS", receipt["status"])
        self.assertEqual("muse-wonder-1.0", receipt["model"])
        self.assertEqual("muse-wonder-1.0", captured[0]["model"])
        self.assertEqual(1, len(captured))
        self.assertEqual(0, receipt["automatic_retries"])

    def test_wonder_model_mismatch_is_not_real_success(self):
        approved = self._approval()
        approved["model"] = "muse-wonder-1.0"
        grant = self.ledger.issue(
            project_id=self.project, prompt=PROMPT, approval=approved,
            verifier=lambda _: True, max_output_tokens=self.out_cap,
            model="muse-wonder-1.0",
        )
        # A transport returning Spark for a Wonder grant is NOT Wonder proof.
        receipt = meta.invoke_with_grant(
            ledger=self.ledger, grant_id=grant["grant_id"],
            project_id=self.project, prompt=PROMPT,
            credential_loader=lambda: "unit-test-placeholder-not-real-key",
            transport=lambda req, timeout: Response(self._response()),
        )
        self.assertNotEqual("REAL_SUCCESS", receipt["status"])
        self.assertEqual("MODEL_MISMATCH", receipt["error_type"])

    def test_wonder_ha_scope_signature_binds_model_and_expiry(self):
        secret = "unit-test-only-not-a-real-approval"
        expiry = int(time.time()) + 120
        prompt_sha = meta._sha(PROMPT.encode("utf-8"))
        ref = "approved-unit-test-wonder"
        signed = f"{ref}|{self.project}|muse-wonder-1.0|{prompt_sha}|{self.out_cap}|{expiry}"
        scope = {
            "approval_ref": ref, "project_id": self.project,
            "prompt_sha256": prompt_sha, "model": "muse-wonder-1.0",
            "max_output_tokens": self.out_cap, "expires_epoch": expiry,
            "owner_actor": "RAFAEL",
            "signature": hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest(),
        }
        with patch.dict(os.environ, {"INNEROS_HA_COMPANION_RECEIPT_SECRET": secret}):
            self.assertTrue(meta.verify_ha_owner_approval(scope))
            fake_mongo = MagicMock()
            fake_mongo.get_db.side_effect = RuntimeError("no trusted grant DB")
            with patch.dict("sys.modules", {"raphiia_openai.mongo_store": fake_mongo}):
                self.assertFalse(meta.verify_ha_owner_approval(dict(scope, model="muse-spark-1.3")))
                self.assertFalse(meta.verify_ha_owner_approval(dict(scope, expires_epoch=expiry + 20)))
                self.assertFalse(meta.verify_ha_owner_approval(dict(scope, signature="")))

    def test_mcp_wonder_selection_is_explicit_and_rejects_unknown(self):
        from inneros_core_runtime import capability_gateway_model as cgm
        ledger = MagicMock()
        ledger.issue.return_value = {
            "grant_id": "grant-test-mock", "model": "muse-wonder-1.0",
        }
        with patch.object(meta, "MetaGrantLedger", return_value=ledger):
            result = cgm._frontier_reason_handler({
                "action": "issue_grant", "model": "muse-wonder-1.0",
                "project_id": self.project, "prompt": PROMPT,
                "approval": self._approval(),
                "max_output_tokens": self.out_cap,
            }, {})
            self.assertTrue(result["ok"])
            self.assertEqual("muse-wonder-1.0", ledger.issue.call_args.kwargs["model"])
            ledger.issue.reset_mock()
            result = cgm._frontier_reason_handler({
                "action": "issue_grant", "model": "unregistered-expensive-model",
                "project_id": self.project, "prompt": PROMPT,
            }, {})
            self.assertFalse(result["ok"])
            self.assertEqual("meta_model_not_allowlisted", result["error"])
            ledger.issue.assert_not_called()
        specs = cgm.get_model_capabilities_specs()
        manifest = next(m for m, _ in specs if m["capability_id"] == "model.frontier.reason.v1")
        self.assertEqual(
            ["muse-spark-1.3", "muse-wonder-1.0"],
            manifest["parameters_schema"]["properties"]["model"]["enum"],
        )
        status = meta.provider_status()
        self.assertIn("muse-wonder-1.0", status["supported_models"])
        self.assertFalse(status["muse_wonder_eligible"])



    def test_wonder_receipt_persists_actual_model_and_supports_allowlisted_tool_calls(self):
        approved = self._approval()
        approved["model"] = "muse-wonder-1.0"
        grant = self.ledger.issue(
            project_id=self.project, prompt=PROMPT, approval=approved,
            verifier=lambda _: True, max_output_tokens=self.out_cap,
            model="muse-wonder-1.0",
        )
        tool_resp = {
            "id": "resp_wonder_tool_call_01",
            "model": "muse-wonder-1.0",
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_ncp_01",
                    "name": "get_ncp_state",
                    "arguments": "{\"include_workers\": true}",
                }
            ],
            "usage": {"input_tokens": 120, "output_tokens": 45, "total_tokens": 165},
        }
        captured = []
        def fake_transport(req, timeout):
            captured.append(json.loads(req.data.decode("utf-8")))
            return Response(tool_resp)

        receipt = meta.invoke_with_grant(
            ledger=self.ledger, grant_id=grant["grant_id"],
            project_id=self.project, prompt=PROMPT,
            tools=[{"name": "get_ncp_state", "description": "Inspect NCP state", "parameters": {"type": "object", "properties": {}}}],
            credential_loader=lambda: "unit-test-placeholder-not-real-key",
            transport=fake_transport,
        )
        self.assertEqual("TOOL_CALL_REQUESTED", receipt["status"])
        self.assertEqual("muse-wonder-1.0", receipt["model"])
        self.assertEqual(1, len(receipt["tool_calls"]))
        self.assertEqual("get_ncp_state", receipt["tool_calls"][0]["name"])
        self.assertEqual({"include_workers": True}, receipt["tool_calls"][0]["arguments"])
        self.assertEqual("get_ncp_state", captured[0]["tools"][0]["name"])

        saved = self.ledger.last_receipt(grant["grant_id"])
        self.assertEqual("muse-wonder-1.0", saved["model"])

        # Unallowlisted tools must fail-closed before consuming or dispatching
        approved2 = self._approval()
        approved2["approval_ref"] = "approved-unit-test-2"
        approved2["model"] = "muse-wonder-1.0"
        grant2 = self.ledger.issue(
            project_id=self.project, prompt=PROMPT, approval=approved2,
            verifier=lambda _: True, max_output_tokens=self.out_cap,
            model="muse-wonder-1.0",
        )
        with self.assertRaises(PermissionError):
            meta.invoke_with_grant(
                ledger=self.ledger, grant_id=grant2["grant_id"],
                project_id=self.project, prompt=PROMPT,
                tools=[{"name": "arbitrary_shell_exec", "description": "Forbidden"}],
                credential_loader=lambda: "unit-test-placeholder-not-real-key",
                transport=fake_transport,
            )


if __name__ == "__main__":
    unittest.main()
