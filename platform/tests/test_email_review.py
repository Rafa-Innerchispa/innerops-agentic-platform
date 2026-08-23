import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

from raphiia_openai.notifications import email_review


class TestEmailReview(unittest.TestCase):
    def test_marketing_does_not_match_payment_inside_memorable(self):
        result = email_review.analyze_email(
            {
                "subject": "Una semana increíble merece un cierre memorable",
                "snippet": "Promoción de nuestra tienda en línea con descuento.",
            }
        )
        self.assertEqual(result["category"], "marketing")
        self.assertEqual(result["priority"], "low")
        self.assertFalse(result.get("alert"))

    def test_bank_notification_is_high(self):
        result = email_review.analyze_email(
            {
                "subject": "Estado de cuenta — Banco Pichincha",
                "from_addr": "alertas@pichincha.com",
                "snippet": "Su extracto bancario del mes está disponible.",
            }
        )
        self.assertEqual(result["priority"], "high")
        self.assertTrue(result.get("alert"))

    def test_smartbrief_junk_low(self):
        result = email_review.analyze_email(
            {
                "subject": "Watch an ad and play Xbox",
                "from_addr": "CTA SmartBrief <cta@smartbrief.com>",
                "snippet": "Newsletter gaming deals unsubscribe",
            }
        )
        self.assertEqual(result["priority"], "low")

    def test_produbanco_promo_is_low(self):
        result = email_review.analyze_email(
            {
                "subject": "Disfruta tus jueves con beneficios exclusivos",
                "from_addr": "noreply@produbanco.com",
                "snippet": "Promoción exclusiva Produbanco.",
            }
        )
        self.assertEqual(result["priority"], "low")
        self.assertFalse(result.get("alert"))

    def test_produbanco_transaction_is_high(self):
        result = email_review.analyze_email(
            {
                "subject": "Consumo Tarjeta de Crédito por USD 27.40",
                "from_addr": "alertas@produbanco.com",
                "snippet": "Se registró un cargo en su tarjeta.",
            }
        )
        self.assertEqual(result["priority"], "high")
        self.assertTrue(result.get("alert"))

    def test_delivery_failure_has_grounded_actions(self):
        result = email_review.analyze_email(
            {"subject": "Mail delivery failed", "snippet": "The recipient address was rejected."}
        )
        self.assertEqual(result["category"], "delivery_failure")
        self.assertEqual(result["priority"], "high")
        self.assertIn("dirección", " ".join(result["suggested_actions"]))

    def test_extracts_plain_body_and_attachment_metadata(self):
        raw = (
            b"MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=x\r\n\r\n"
            b"--x\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nMensaje de prueba.\r\n"
            b"--x\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=test.pdf\r\n\r\nPDF\r\n--x--\r\n"
        )
        message = BytesParser(policy=policy.default).parsebytes(raw)
        body, attachments = email_review._extract_body(message)
        self.assertIn("Mensaje de prueba", body)
        self.assertEqual(attachments[0]["filename"], "test.pdf")

    def test_prepare_reply_never_sends_without_confirmation(self):
        review = {
            "ok": True,
            "message": {
                "mail_id": "mail_fixture",
                "from_addr": "Fixture <fixture@example.test>",
                "subject": "Prueba aislada",
                "account_address": "owner@example.test",
            },
        }
        with patch.object(email_review, "get_review", return_value=review):
            result = email_review.prepare_reply("mail_fixture", "Respuesta ficticia")
        self.assertTrue(result["ok"])
        self.assertEqual(result["payload"]["to_addr"], "fixture@example.test")
        self.assertIn("¿Confirmas", result["preview"])


if __name__ == "__main__":
    unittest.main()
