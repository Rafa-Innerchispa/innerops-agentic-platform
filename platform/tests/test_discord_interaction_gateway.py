from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from raphiia_openai import discord_interaction_gateway as gateway


class DiscordInteractionGatewayTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        public = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key = public.hex()

    def _signed(self, payload: dict):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = self.private_key.sign(timestamp.encode("utf-8") + raw).hex()
        return raw, signature, timestamp

    def test_ping_returns_pong_after_signature_verification(self):
        raw, signature, timestamp = self._signed({"type": gateway.INTERACTION_PING})
        with mock.patch.object(gateway.local_discord_plane, "_config", return_value={"public_key": self.public_key}):
            status, body = gateway.handle_interaction(raw, signature, timestamp)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"type": gateway.RESPONSE_PONG})

    def test_bad_signature_is_rejected(self):
        raw, _signature, timestamp = self._signed({"type": gateway.INTERACTION_PING})
        with mock.patch.object(gateway.local_discord_plane, "_config", return_value={"public_key": self.public_key}):
            status, body = gateway.handle_interaction(raw, "00" * 64, timestamp)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "bad_request_signature")

    def test_status_command_does_not_execute_arbitrary_work(self):
        payload = {"type": gateway.INTERACTION_APPLICATION_COMMAND, "data": {"name": "inneros-status"}}
        raw, signature, timestamp = self._signed(payload)
        with mock.patch.object(gateway.local_discord_plane, "_config", return_value={"public_key": self.public_key}), mock.patch.object(
            gateway, "endpoint_status", return_value={"bot_auth_ok": True}
        ):
            status, body = gateway.handle_interaction(raw, signature, timestamp)
        self.assertEqual(status, 200)
        self.assertEqual(body["type"], gateway.RESPONSE_CHANNEL_MESSAGE)
        self.assertIn("activo", body["data"]["content"])

    def test_unknown_command_is_allowlist_rejected(self):
        payload = {"type": gateway.INTERACTION_APPLICATION_COMMAND, "data": {"name": "shell"}}
        raw, signature, timestamp = self._signed(payload)
        with mock.patch.object(gateway.local_discord_plane, "_config", return_value={"public_key": self.public_key}):
            status, body = gateway.handle_interaction(raw, signature, timestamp)
        self.assertEqual(status, 200)
        self.assertIn("no reconocido", body["data"]["content"])


if __name__ == "__main__":
    unittest.main()
