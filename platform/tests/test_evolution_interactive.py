import unittest
from types import SimpleNamespace
from unittest.mock import patch

from raphiia_openai.notifications import evolution_client


class TestEvolutionInteractive(unittest.TestCase):
    def test_successful_button_delivery_also_sends_plain_text_challenge(self):
        response = SimpleNamespace(status_code=200, json=lambda: {"key": {"id": "fixture"}}, text="")
        fallback = {"ok": True, "status": "sent"}
        with patch.object(evolution_client, "EVOLUTION_API_KEY", "fixture"), patch.object(
            evolution_client, "_node_config", return_value=("http://evolution.test", "fixture-instance")
        ), patch.object(evolution_client.httpx, "post", return_value=response), patch.object(
            evolution_client, "send_whatsapp", return_value=fallback
        ) as send_text, patch(
            "raphiia_openai.whatsapp_message_ledger.record_outbound", return_value={"ok": True}
        ):
            result = evolution_client.send_whatsapp_interactive(
                "Confirma operación ABC123",
                [{"id": "maint.confirm.ABC123", "label": "Confirmar"}],
                number="593000000000",
                fallback_text="Confirma con: confirmar ABC123",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["delivery_mode"], "interactive_plus_text")
        send_text.assert_called_once()
        self.assertIn("confirmar ABC123", send_text.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
