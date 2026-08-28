import unittest

from raphiia_openai.quoteops_iess_bridge import (
    extract_message_id,
    is_iess_payment_image,
    parse_iess_action,
)
from raphiia_openai.whatsapp_evolution_parse import sanitize_payload_for_storage


class TestWhatsappIessBridge(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "apikey": "must-not-persist",
            "data": {
                "key": {"id": "MESSAGE-1", "remoteJid": "593999@s.whatsapp.net"},
                "message": {
                    "imageMessage": {
                        "caption": "Pago IESS",
                        "mediaKey": "secret-media-key",
                        "directPath": "/encrypted-media",
                        "jpegThumbnail": "base64-thumbnail",
                        "mimetype": "image/jpeg",
                    }
                },
            },
        }

    def test_detects_iess_image_and_message_id(self):
        self.assertTrue(is_iess_payment_image(self.payload, "Pago IESS"))
        self.assertEqual(extract_message_id(self.payload), "MESSAGE-1")

    def test_requires_image(self):
        self.assertFalse(is_iess_payment_image({"data": {"message": {}}}, "Pago IESS"))

    def test_parses_only_typed_confirmation(self):
        self.assertEqual(parse_iess_action("CONFIRMAR PAGO iesspay_0123456789abcdef"), ("confirm", "iesspay_0123456789abcdef"))
        self.assertEqual(parse_iess_action("cancelar pago iesspay_0123456789abcdef"), ("cancel", "iesspay_0123456789abcdef"))
        self.assertIsNone(parse_iess_action("confirmar todo"))

    def test_sanitizes_transport_secrets_but_keeps_audit_fields(self):
        clean = sanitize_payload_for_storage(self.payload)
        self.assertNotIn("apikey", clean)
        image = clean["data"]["message"]["imageMessage"]
        self.assertNotIn("mediaKey", image)
        self.assertNotIn("directPath", image)
        self.assertNotIn("jpegThumbnail", image)
        self.assertEqual(image["caption"], "Pago IESS")
        self.assertEqual(clean["data"]["key"]["id"], "MESSAGE-1")


if __name__ == "__main__":
    unittest.main()
