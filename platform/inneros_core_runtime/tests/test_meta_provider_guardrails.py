"""Meta como proveedor externo con guardarraíl anti-quema de créditos.

Meta no tiene CLI local ni worker headless systemd: solo corre vía grant
one-shot del owner (MetaGrantLedger). Estas pruebas fijan que:
- el registry lo trata como interactivo con despacho manual por defecto,
- el gobernador de créditos lo cubre con límites conservadores,
- correr sin aprobación explícita se niega,
- el headless pago lo rechaza (fail-closed).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from inneros_core_runtime import agent_provider_registry as apr
from inneros_core_runtime import external_repair_agent as ext
from inneros_core_runtime import ops_headless_execution_policy as ohp


class MetaProviderGuardrailTests(unittest.TestCase):
    def test_meta_defaults_to_manual_dispatch(self):
        self.assertIn("meta", apr.interactive_providers())
        lane, prov, do_not = apr.apply_create_ops_defaults(
            "meta", execution_lane=None, preferred_provider=None, do_not_auto_dispatch=None
        )
        self.assertEqual(prov, "meta")
        self.assertEqual(lane, "meta_interactive")
        self.assertTrue(do_not)

    def test_meta_credit_limits_are_conservative_defaults(self):
        with patch.object(ext.mongo_store, "get_coordination_state", return_value={"ok": False}):
            cfg = ext._credit_config()
        self.assertEqual(cfg["daily_hard_limit"]["meta"], 2)
        self.assertEqual(cfg["monthly_hard_limit"]["meta"], 20)

    def test_meta_detect_is_supported_but_never_ready_without_grant(self):
        with patch("shutil.which", return_value=None):
            result = ext.detect_provider("meta")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "meta")
        self.assertFalse(result["installed"])
        self.assertEqual(result["status"], "unavailable")

    def test_meta_run_requires_explicit_spend_approval(self):
        with patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}}):
            result = ext.external_repair_agent_run_task("meta", "ops_fixture", dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "external_spend_approval_required")

    def test_meta_paid_headless_is_denied_fail_closed(self):
        task = {
            "task_id": "ops_meta_probe",
            "status": "in_progress",
            "assignee": "meta",
            "claim_token": "tok",
            "owner_authorized_at": "2026-10-29T00:00:00Z",
            "payload": {},
            "execution_lane": "meta_interactive",
        }
        self.assertEqual(ohp.headless_denial(task), "unsupported_paid_provider")


if __name__ == "__main__":
    unittest.main()
