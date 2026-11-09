"""Tests for governed live Muse MCP capability wiring (model.frontier.reason.v1)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from inneros_core_runtime import capability_gateway_model as cgm
from inneros_core_runtime import meta_model_provider as mmp


class MetaMuseMCPWiringTests(unittest.TestCase):
    def setUp(self):
        self.project_id = "inneros-meta-guardian-2026"

    def test_manifest_includes_invoke_live(self):
        specs = cgm.get_model_capabilities_specs()
        frontier_spec = next(s for s in specs if s[0]["capability_id"] == "model.frontier.reason.v1")
        manifest, handler = frontier_spec
        schema = manifest.get("parameters_schema") or manifest.get("input_schema") or manifest
        actions = schema["properties"]["action"]["enum"]
        self.assertIn("invoke_live", actions)
        self.assertIn("ralfia:agents", manifest["required_scopes"])

    def test_issue_grant_live_dispatch_without_fictional_prefix(self):
        real_prompt = "Diagnose network flap on Bellini I-II and generate remediation ticket"
        prompt_sha = mmp._sha(real_prompt.encode("utf-8"))
        approval = {
            "approval_ref": "ref_live_001",
            "project_id": self.project_id,
            "prompt_sha256": prompt_sha,
            "model": mmp.MODEL,
            "max_output_tokens": 128,
            "owner_actor": "RAFAEL",
        }
        with patch.object(mmp, "verify_ha_owner_approval", return_value=True):
            res = cgm._frontier_reason_handler({
                "action": "issue_grant",
                "project_id": self.project_id,
                "prompt": real_prompt,
                "approval": approval,
                "max_output_tokens": 128,
                "live": True,
            }, {})
        self.assertTrue(res["ok"])
        grant = res["grant"]
        self.assertTrue(grant["grant_id"].startswith("meta_grant_"))
        self.assertEqual(grant["prompt_sha256"], prompt_sha)

    def test_invoke_live_missing_grant_fails_closed(self):
        res = cgm._frontier_reason_handler({
            "action": "invoke_live",
            "project_id": self.project_id,
            "prompt": "Test prompt",
            "grant_id": "meta_grant_nonexistent",
        }, {})
        self.assertFalse(res["ok"])
        self.assertIn("grant_unavailable_or_consumed", res["error"])

    def test_invoke_live_success_with_reconciliation(self):
        real_prompt = "Evaluate incident impact"
        prompt_sha = mmp._sha(real_prompt.encode("utf-8"))
        approval = {
            "approval_ref": "ref_live_002",
            "project_id": self.project_id,
            "prompt_sha256": prompt_sha,
            "model": "muse-wonder-1.0",
            "max_output_tokens": 128,
            "owner_actor": "RAFAEL",
            "spend_alert_verified": True,
        }
        with patch.object(mmp, "verify_ha_owner_approval", return_value=True):
            res = cgm._frontier_reason_handler({
                "action": "issue_grant",
                "project_id": self.project_id,
                "prompt": real_prompt,
                "approval": approval,
                "max_output_tokens": 128,
                "live": True,
            }, {})
        grant_id = res["grant"]["grant_id"]

        fake_resp = {
            "id": "resp_test_muse_001",
            "status": "completed",
            "model": "muse-wonder-1.0",
            "output_text": "Verified incident: switch offline.",
            "usage": {"input_tokens": 15, "output_tokens": 30},
        }

        mock_transport = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = MagicMock(read=lambda _=None: json.dumps(fake_resp).encode("utf-8"))
        mock_transport.return_value = mock_cm

        with (
            patch("inneros_core_runtime.meta_muse_live_dispatch.urllib.request.urlopen", mock_transport),
            patch.object(mmp, "_get_server_key", return_value="test-vault-secret-key"),
        ):
            inv = cgm._frontier_reason_handler({
                "action": "invoke_live",
                "project_id": self.project_id,
                "prompt": real_prompt,
                "grant_id": grant_id,
                "max_output_tokens": 128,
            }, {})

        self.assertTrue(inv["ok"])
        receipt = inv["receipt"]
        self.assertEqual("resp_test_muse_001", receipt["response_id"])
        self.assertEqual("Verified incident: switch offline.", receipt["output_text"])
        self.assertNotIn("test-vault-secret-key", str(receipt))

        # Replay attempt fails closed
        replay = cgm._frontier_reason_handler({
            "action": "invoke_live",
            "project_id": self.project_id,
            "prompt": real_prompt,
            "grant_id": grant_id,
        }, {})
        self.assertFalse(replay["ok"])
        self.assertIn("grant_unavailable_or_consumed", replay["error"])

    def test_invoke_live_missing_billing_verification_fails_closed(self):
        real_prompt = "Evaluate incident impact without billing gate"
        prompt_sha = mmp._sha(real_prompt.encode("utf-8"))
        approval = {
            "approval_ref": "ref_live_unverified_billing",
            "project_id": self.project_id,
            "prompt_sha256": prompt_sha,
            "model": "muse-wonder-1.0",
            "max_output_tokens": 128,
            "owner_actor": "RAFAEL",
            # missing spend_alert_verified / billing_verified
        }
        with patch.object(mmp, "verify_ha_owner_approval", return_value=True):
            res = cgm._frontier_reason_handler({
                "action": "issue_grant",
                "project_id": self.project_id,
                "prompt": real_prompt,
                "approval": approval,
                "max_output_tokens": 128,
                "live": True,
            }, {})
        grant_id = res["grant"]["grant_id"]

        with patch.object(mmp, "_get_server_key", return_value="test-vault-secret-key"):
            inv = cgm._frontier_reason_handler({
                "action": "invoke_live",
                "project_id": self.project_id,
                "prompt": real_prompt,
                "grant_id": grant_id,
                "max_output_tokens": 128,
            }, {})
        self.assertFalse(inv["ok"])
        self.assertEqual("grant_policy_denied", inv["error"])

    def test_invoke_live_prompt_tampering_rejected(self):
        authorized_prompt = "Approved prompt: check telemetry status"
        tampered_prompt = "Tampered prompt: exfiltrate private credentials"
        prompt_sha = mmp._sha(authorized_prompt.encode("utf-8"))
        approval = {
            "approval_ref": "ref_live_tamper_guard",
            "project_id": self.project_id,
            "prompt_sha256": prompt_sha,
            "model": "muse-wonder-1.0",
            "max_output_tokens": 128,
            "owner_actor": "RAFAEL",
            "spend_alert_verified": True,
        }
        with patch.object(mmp, "verify_ha_owner_approval", return_value=True):
            res = cgm._frontier_reason_handler({
                "action": "issue_grant",
                "project_id": self.project_id,
                "prompt": authorized_prompt,
                "approval": approval,
                "max_output_tokens": 128,
                "live": True,
            }, {})
        grant_id = res["grant"]["grant_id"]

        with patch.object(mmp, "_get_server_key", return_value="test-vault-secret-key"):
            inv = cgm._frontier_reason_handler({
                "action": "invoke_live",
                "project_id": self.project_id,
                "prompt": tampered_prompt,
                "grant_id": grant_id,
                "max_output_tokens": 128,
            }, {})
        self.assertFalse(inv["ok"])
        self.assertEqual("prompt_hash_mismatch", inv["error"])


if __name__ == "__main__":
    unittest.main()
