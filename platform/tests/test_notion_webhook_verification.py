import hashlib
import hmac
import json
import unittest
from unittest import mock

from raphiia_openai import notion_webhook


class NotionWebhookVerificationTests(unittest.TestCase):
    def test_webhook_uses_stored_verification_token_when_env_missing(self):
        payload = {"type": "comment.created", "entity": {"id": "comment-1"}}
        raw = json.dumps(payload).encode("utf-8")
        secret = "stored-secret-for-test"
        signature = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        fake_db = {
            notion_webhook.CONFIG_COL: mock.Mock(find_one=mock.Mock(return_value={"verification_token": secret})),
        }
        fake_db[notion_webhook.EVENTS_COL] = mock.Mock(insert_one=mock.Mock(return_value=None))
        with mock.patch.object(notion_webhook, "NOTION_WEBHOOK_VERIFICATION_TOKEN", ""), \
            mock.patch.object(notion_webhook.mongo_store, "get_db", return_value=fake_db), \
            mock.patch.object(notion_webhook.mongo_store, "log_sync", return_value=None):
            result = notion_webhook.handle_notion_webhook(raw, signature=signature)
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["verification_token_source"], "mongo_pending")

    def test_webhook_rejects_bad_signature_with_stored_token(self):
        raw = json.dumps({"type": "comment.created"}).encode("utf-8")
        fake_db = {
            notion_webhook.CONFIG_COL: mock.Mock(find_one=mock.Mock(return_value={"verification_token": "stored-secret"})),
        }
        with mock.patch.object(notion_webhook, "NOTION_WEBHOOK_VERIFICATION_TOKEN", ""), \
            mock.patch.object(notion_webhook.mongo_store, "get_db", return_value=fake_db):
            result = notion_webhook.handle_notion_webhook(raw, signature="sha256=bad")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_signature")


if __name__ == "__main__":
    unittest.main()
