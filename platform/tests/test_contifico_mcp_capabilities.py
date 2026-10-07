"""Tests for Contifico billing + MCP capabilities (mocked HTTP)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from inneros_core_runtime import contifico_billing as bill
from inneros_core_runtime.capability_gateway import capability_describe, capability_invoke, capability_search


class ContificoBillingTests(unittest.TestCase):
    def test_connection_status_without_key(self) -> None:
        with patch.object(bill, "_api_key_for", return_value=""):
            st = bill.connection_status()
        self.assertFalse(st["ok"])
        self.assertFalse(st["configured"])

    def test_iva_calc_15_percent(self) -> None:
        calc = bill._calc_iva_lines([{"descripcion": "Soporte", "cantidad": 1, "precio": 100, "porcentaje_iva": 15}])
        self.assertEqual(calc["subtotal"], 100.0)
        self.assertEqual(calc["iva"], 15.0)
        self.assertEqual(calc["total"], 115.0)

    def test_invoice_create_requires_owner_approval(self) -> None:
        res = bill.invoice_create(
            persona_id="pid1",
            lines=[{"descripcion": "X", "precio": 1, "cantidad": 1}],
            owner_approved=False,
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "owner_approval_required")

    def test_sanitize_redacts_token_like_text(self) -> None:
        text = bill._sanitize_text("Authorization: supersecretkey123")
        self.assertNotIn("supersecretkey123", text)

    @patch.object(bill, "_request")
    def test_customer_search_api(self, mock_req: MagicMock) -> None:
        mock_req.return_value = {
            "ok": True,
            "data": [{"id": "p1", "cedula": "0914832423", "razon_social": "Rafael Test", "ruc": "0914832423001"}],
        }
        res = bill.customer_search(cedula="0914832423", max_pages=1)
        self.assertTrue(res["ok"])
        self.assertEqual(res["count"], 1)

    @patch.object(bill, "_idempotency_get", return_value={"contifico_document_id": "doc_cached"})
    @patch.object(bill, "_request")
    def test_invoice_draft_idempotent(self, mock_req: MagicMock, _mock_idem: MagicMock) -> None:
        res = bill.invoice_draft(
            persona_id="p1",
            lines=[{"descripcion": "Test", "precio": 1, "cantidad": 1}],
            idempotency_key="idem-1",
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("idempotent"))
        mock_req.assert_not_called()

    @patch.object(bill, "customer_search")
    def test_customer_create_duplicate_blocked(self, mock_search: MagicMock) -> None:
        mock_search.return_value = {"ok": True, "count": 1, "customers": [{"persona_id": "existing"}]}
        res = bill.customer_create({"cedula": "0914832423", "razon_social": "X"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "duplicate_customer")



    def test_resolve_entity_aliases(self) -> None:
        from inneros_core_runtime import contifico_entities as ent
        e = ent.resolve_entity("innerchispa")
        self.assertEqual(e.entity_id, "domotika")

    @patch.object(bill, "_connection_status_one")
    def test_connection_status_all_entities(self, mock_one) -> None:
        mock_one.side_effect = [
            {"entity_id": "pcdoctor", "ok": True, "configured": True, "connected": True},
            {"entity_id": "domotika", "ok": False, "configured": False, "connected": False},
        ]
        st = bill.connection_status()
        self.assertTrue(st["ok"])
        self.assertEqual(len(st["entities"]), 2)
        self.assertIn("registry", st)

    def test_ledger_entity_scoped(self) -> None:
        from inneros_core_runtime.operational.accounting_ledger import ledger_from_contifico
        doc = ledger_from_contifico({
            "contifico_entity_id": "domotika",
            "contifico_id": "abc123",
            "tipo_documento": "FAC",
            "documento": "001",
            "issuer_ruc": "0914832423001",
        })
        self.assertEqual(doc["ledger_id"], "contifico:domotika:abc123")
        self.assertEqual(doc["contifico_entity_id"], "domotika")

class ContificoCapabilityRegistryTests(unittest.TestCase):
    def test_capabilities_discoverable(self) -> None:
        res = capability_search(query="contifico", max_results=20)
        self.assertTrue(res["ok"])
        ids = {c["capability_id"] for c in res["capabilities"]}
        self.assertIn("contifico.connection.status.v1", ids)
        self.assertIn("contifico.invoice.draft.v1", ids)

    def test_describe_draft_capability(self) -> None:
        res = capability_describe("contifico.invoice.draft.v1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["capability"]["risk_class"], "medium")

    @patch.object(bill, "connection_status", return_value={"ok": True, "connected": True})
    def test_invoke_connection_status(self, _mock: MagicMock) -> None:
        res = capability_invoke("contifico.connection.status.v1", {})
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()
