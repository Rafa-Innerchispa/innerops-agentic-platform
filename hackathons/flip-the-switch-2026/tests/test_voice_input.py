"""Dictation text never authorizes physical changes on its own."""
import unittest

from inneros_incident_room.voice_input import to_safe_room_command
from inneros_incident_room.live_homeassistant import LiveRoomPolicy
from test_live_homeassistant import FakeHA, frame, ROOM, OWNER, LIGHT


class VoiceMappingTests(unittest.TestCase):
    def test_spanish_queries(self):
        for phrase in (
            "Que luces hay?", "\u00bfQu\u00e9 luces hay?", "Muestrame las luces, por favor.",
            "Listar luces", "Mostrar las luces",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(to_safe_room_command(phrase), "!lights")

    def test_explicit_entity_required(self):
        self.assertEqual(to_safe_room_command("Estado de light.demo_lamp"), "!state light.demo_lamp")
        self.assertEqual(to_safe_room_command("Propongo encender light.demo_lamp"), "!propose light.demo_lamp on")
        self.assertEqual(to_safe_room_command("Proponer apagar light.demo_lamp"), "!propose light.demo_lamp off")
        self.assertEqual(to_safe_room_command("Consulta InnerOS"), "!inneros")

    def test_ambiguous_commands_not_expanded(self):
        for phrase in ("enciende la luz", "enciende todas las luces", "aprobado", "aprueba la orden", "ok hazlo"):
            with self.subTest(phrase=phrase):
                self.assertEqual(to_safe_room_command(phrase), phrase)

    def test_no_mutation_from_voice_proposal_and_denial(self):
        ha = FakeHA()
        policy = LiveRoomPolicy(ROOM, OWNER, ha, frozenset({LIGHT}),
                                actions_enabled=True, id_factory=lambda: "voice1", clock=lambda: 1000)
        self.assertIn("[HA LIVE]", policy.handle(frame("\u00bfQu\u00e9 luces hay?")))
        self.assertIn("[HA LIVE READ]", policy.handle(frame("Estado de light.demo_lamp", mid="v2")))
        self.assertIn("HA-voice1", policy.handle(frame("Propongo encender light.demo_lamp", mid="v3")))
        self.assertEqual(ha.writes, [])
        self.assertIn("Commands:", policy.handle(frame("aprobado", mid="v4")))
        self.assertEqual(ha.writes, [])
        self.assertIn("DENIED", policy.handle(frame("!deny HA-voice1", mid="v5")))
        self.assertEqual(ha.writes, [])

    def test_untrusted_sender_voice_proposal_blocked(self):
        ha = FakeHA()
        policy = LiveRoomPolicy(ROOM, OWNER, ha, frozenset({LIGHT}),
                                actions_enabled=True, id_factory=lambda: "voice2", clock=lambda: 1000)
        out = policy.handle(frame("Propongo encender light.demo_lamp", sender="@other:local"))
        self.assertIn("BLOCKED", out)
        self.assertEqual(ha.writes, [])

    def test_mention_prefix_keeps_policy(self):
        ha = FakeHA()
        policy = LiveRoomPolicy(ROOM, OWNER, ha, frozenset({LIGHT}),
                                actions_enabled=True, clock=lambda: 1000)
        out = policy.handle(frame("@inneros-incidentes Que luces hay?"))
        self.assertIn("[HA LIVE]", out)


if __name__ == "__main__":
    unittest.main()