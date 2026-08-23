import unittest

from raphiia_openai import whatsapp_conversational


class TestWhatsappConversationalGrounding(unittest.TestCase):
    def test_image_claim_is_blocked_when_message_was_audio_only(self):
        text, grounding = whatsapp_conversational._validate_grounded_response(
            "No puedo ejecutar comandos de imágenes no confiables.",
            [{"source": "audio_transcript"}],
        )
        self.assertEqual(grounding["status"], "blocked")
        self.assertIn("media_not_received", grounding["reasons"])
        self.assertIn("No recibí una imagen", text)

    def test_panel_failure_requires_health_evidence(self):
        _, blocked = whatsapp_conversational._validate_grounded_response(
            "El panel está down.", []
        )
        self.assertIn("unsupported_operational_claim", blocked["reasons"])
        _, grounded = whatsapp_conversational._validate_grounded_response(
            "El panel está down.", [{"source": "health_snapshot"}]
        )
        self.assertEqual(grounded["status"], "grounded")


if __name__ == "__main__":
    unittest.main()
