"""Offline security tests for governed Muse call adapter."""
from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inneros_core_runtime.meta_muse_live_dispatch import (  # noqa: E402
    API_URL, MODEL, MuseDispatchError, MuseGrant, invoke_muse,
)


class FakeStore:
    def __init__(self, grant):
        self.grant = grant
        self.consumed = False

    def redeem_once(self, grant_id):
        if self.consumed or grant_id != self.grant.grant_id:
            raise RuntimeError("already consumed")
        self.consumed = True
        return self.grant


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class MuseDispatchTests(unittest.TestCase):
    def setUp(self):
        self.grant = MuseGrant(
            grant_id="g-1",
            project_id="inneros-coordination",
            provider="meta",
            model=MODEL,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            max_output_tokens=200,
            max_prompt_chars=1000,
            max_cost_usd=0.1,
            owner_approved=True,
            billing_hard_limit_verified=True,
        )
        self.calls = []

    def send(self, req, timeout):
        self.calls.append((req, timeout))
        return Response(json.dumps({
            "id": "resp_test",
            "status": "completed",
            "model": MODEL,
            "output": [{"content": [{"type": "output_text", "text": "PONG"}]}],
            "usage": {"total_tokens": 4},
        }).encode())

    def invoke(self, grant=None, prompt="Test coordination", transport=None):
        return invoke_muse(
            prompt=prompt,
            grant_id="g-1",
            grant_store=FakeStore(grant or self.grant),
            resolve_api_key=lambda: "fake-secret",
            requested_output_tokens=100,
            transport=transport or self.send,
        )

    def test_live_path_one_call_and_redacted_receipt(self):
        result = self.invoke()
        self.assertEqual(result["output_text"], "PONG")
        self.assertEqual(result["response_id"], "resp_test")
        self.assertEqual(len(self.calls), 1)
        req, timeout = self.calls[0]
        self.assertEqual(req.full_url, API_URL)
        self.assertEqual(req.get_method(), "POST")
        payload = json.loads(req.data)
        self.assertEqual(payload["model"], MODEL)
        self.assertNotIn("fake-secret", json.dumps(result))
        self.assertEqual(timeout, 45)

    def test_replay_denied(self):
        store = FakeStore(self.grant)
        kwargs = dict(
            prompt="Inspect ACK", grant_id="g-1", grant_store=store,
            resolve_api_key=lambda: "fake-secret", transport=self.send,
        )
        invoke_muse(**kwargs)
        with self.assertRaisesRegex(MuseDispatchError, "consumed"):
            invoke_muse(**kwargs)
        self.assertEqual(len(self.calls), 1)

    def test_missing_owner_approval_denied(self):
        with self.assertRaisesRegex(MuseDispatchError, "policy_denied"):
            self.invoke(grant=replace(self.grant, owner_approved=False))
        self.assertFalse(self.calls)

    def test_missing_billing_hard_limit_denied(self):
        with self.assertRaisesRegex(MuseDispatchError, "policy_denied"):
            self.invoke(grant=replace(self.grant, billing_hard_limit_verified=False))
        self.assertFalse(self.calls)

    def test_expired_grant_denied(self):
        with self.assertRaisesRegex(MuseDispatchError, "policy_denied"):
            self.invoke(grant=replace(self.grant, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        self.assertFalse(self.calls)

    def test_wrong_provider_or_model_denied(self):
        for kwargs in [{"provider": "other"}, {"model": "muse-spark"}]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(MuseDispatchError, "policy_denied"):
                    self.invoke(grant=replace(self.grant, **kwargs))
        self.assertFalse(self.calls)

    def test_long_prompt_denied_before_redeem(self):
        with self.assertRaisesRegex(MuseDispatchError, "invalid_prompt"):
            self.invoke(prompt="x" * 6001)
        self.assertFalse(self.calls)

    def test_http_errors_hide_provider_body(self):
        def denied(req, timeout):
            raise urllib.error.HTTPError(API_URL, 401, "token=secret", None, None)
        with self.assertRaisesRegex(MuseDispatchError, "^meta_http_401$"):
            self.invoke(transport=denied)

    def test_prompt_hash_mismatch_denied(self):
        grant_with_hash = replace(self.grant, prompt_sha256="0" * 64)
        with self.assertRaisesRegex(MuseDispatchError, "prompt_hash_mismatch"):
            self.invoke(grant=grant_with_hash, prompt="Different prompt")
        self.assertFalse(self.calls)

    def test_spark_model_allowed_when_in_grant(self):
        grant_spark = replace(self.grant, model="muse-spark-1.3")
        res = self.invoke(grant=grant_spark)
        self.assertEqual(res["output_text"], "PONG")
        req, _ = self.calls[-1]
        payload = json.loads(req.data)
        self.assertEqual(payload["model"], "muse-spark-1.3")

    def test_missing_key_denied_without_network(self):
        with self.assertRaisesRegex(MuseDispatchError, "meta_credential_unavailable"):
            invoke_muse(prompt="Test", grant_id="g-1", grant_store=FakeStore(self.grant),
                        resolve_api_key=lambda: "", transport=self.send)
        self.assertFalse(self.calls)


if __name__ == "__main__":
    unittest.main()
