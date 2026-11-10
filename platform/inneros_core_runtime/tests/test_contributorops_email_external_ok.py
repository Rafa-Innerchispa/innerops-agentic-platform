"""Puente ContributorOps: un modulo externo ausente no tumba el ciclo AG-25."""
import os
import unittest
from unittest.mock import patch

from inneros_core_runtime import gitlab_contributorops_email_bridge as bridge
from inneros_core_runtime.notifications import email_ag25_integration as gmail


class ContributorOpsExternalStepTests(unittest.TestCase):
    def test_missing_ingress_returns_external_flag(self):
        env = {
            "CONTRIBUTOROPS_EMAIL_INGRESS": "1",
            "CONTRIBUTOROPS_INNEROS_BRIDGE": "1",
        }
        with (
            patch.dict(os.environ, env),
            patch.object(
                bridge,
                "_agent_imports",
                side_effect=ImportError(
                    "cannot import name 'email_ingress' from 'contributorops'"
                ),
            ),
        ):
            out = bridge.process_recent_gitlab_emails(dry_run=True)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("external"))
        self.assertEqual(out["reason"], "contributorops_email_ingress_missing")

    def test_cycle_ok_ignores_external_failure(self):
        steps = {
            "promote_ops": {"ok": True},
            "contributorops_email": {
                "ok": False,
                "external": True,
                "reason": "contributorops_email_ingress_missing",
            },
        }
        self.assertTrue(gmail.cycle_ok(steps))

    def test_cycle_ok_honors_own_failure(self):
        steps = {
            "promote_ops": {"ok": False, "error": "mongo down"},
            "contributorops_email": {"ok": True},
        }
        self.assertFalse(gmail.cycle_ok(steps))


if __name__ == "__main__":
    unittest.main()
