import unittest

from inneros_core_runtime.notifications import email_intelligence as ei


class TestEmailIntelligenceStrategicSignals(unittest.TestCase):
    def test_xerj_in_promotions_creates_ops_task(self):
        doc = {
            "mail_id": "msg_xerj_test",
            "subject": "XERJ Corpus Hub — founder selected your InnerOS code",
            "body_text": "Ivan N selected InnerOS for the XERJ corpus hub.",
            "gmail_category": "CATEGORY_PROMOTIONS",
        }
        decision = ei.decide_email(doc)
        self.assertNotIn(decision["document_type"], {"spam_newsletter", "fyi"})
        self.assertTrue(decision["create_ops_task"])
        self.assertEqual(decision["document_type"], "lead_cliente")
        self.assertIn("gmail_promotions_override", decision.get("matched_signals") or [])

    def test_ops_loop_noise_stays_fyi(self):
        doc = {
            "mail_id": "msg_ops_noise",
            "subject": "[RalfIA OPS] awaiting_antigravity_claim",
            "body_text": "Please claim the task",
        }
        decision = ei.decide_email(doc)
        self.assertEqual(decision["document_type"], "fyi")
        self.assertFalse(decision["create_ops_task"])

    def test_github_2fa_is_high_priority(self):
        doc = {
            "mail_id": "msg_gh_2fa",
            "subject": "Action required: enable two-factor authentication",
            "body_text": "GitHub requires 2FA for Rafa-Innerchispa before Dec 15 2026.",
        }
        decision = ei.decide_email(doc)
        self.assertEqual(decision["document_type"], "servicio_vencimiento")
        self.assertTrue(decision["create_ops_task"])


if __name__ == "__main__":
    unittest.main()
