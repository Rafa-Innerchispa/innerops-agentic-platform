"""Saludo e identidad owner sin depender de Ollama."""
from __future__ import annotations

import unittest


class OwnerChitchatRepliesTest(unittest.TestCase):
    def test_identity_and_greeting_telegram(self) -> None:
        from inneros_core_runtime.notifications import whatsapp_conversational as wc

        ident = {"verified_owner": True, "role": "owner"}
        who = wc.conversational_reply(
            "quien eres",
            sender="593999059000",
            conversation_id="telegram:unit-test",
            channel="telegram",
            identity=ident,
        )
        self.assertEqual(who.get("source"), "direct_chitchat")
        self.assertIn("RalfIA", who.get("text") or "")
        self.assertNotIn("Te escucho. Cuéntame", who.get("text") or "")

        hola = wc.conversational_reply(
            "hola",
            sender="593999059000",
            conversation_id="telegram:unit-test-2",
            channel="telegram",
            identity=ident,
        )
        self.assertEqual(hola.get("source"), "direct_chitchat")
        self.assertRegex(hola.get("text") or "", r"(?i)en qu[eé] te ayudo|hola")


if __name__ == "__main__":
    unittest.main()
