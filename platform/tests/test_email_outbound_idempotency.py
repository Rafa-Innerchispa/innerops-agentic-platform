import ast
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from pymongo.errors import DuplicateKeyError

_EMAIL_CLIENT_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "notifications" / "email_client.py"
_SPEC = importlib.util.spec_from_file_location("email_client_under_test", _EMAIL_CLIENT_PATH)
assert _SPEC and _SPEC.loader
email_client = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(email_client)


class _FakeCollection:
    def __init__(self):
        self.docs = {}

    def find_one_and_update(self, query, update, upsert=False, return_document=None):
        key = query["_id"]
        now = datetime.now(timezone.utc)
        current = self.docs.get(key)
        if current and current.get("status") in {"reserved", "sent"} and current.get("expires_at", now) > now:
            if upsert:
                raise DuplicateKeyError("duplicate reservation")
            return None
        doc = dict(current or {"_id": key, "attempts": 0})
        doc.update(update["$set"])
        doc["attempts"] = doc.get("attempts", 0) + update.get("$inc", {}).get("attempts", 0)
        for field, value in update.get("$setOnInsert", {}).items():
            doc.setdefault(field, value)
        self.docs[key] = doc
        return dict(doc)

    def find_one(self, query):
        doc = self.docs.get(query["_id"])
        return dict(doc) if doc else None

    def update_one(self, query, update):
        key = query["_id"]
        doc = self.docs[key]
        doc.update(update.get("$set", {}))
        for field in update.get("$unset", {}):
            doc.pop(field, None)


class _FakeDB:
    def __init__(self):
        self.email_outbound_ledger = _FakeCollection()

    def __getitem__(self, name):
        return getattr(self, name)


class TestEmailOutboundIdempotency(unittest.TestCase):
    def setUp(self):
        self.db = _FakeDB()
        self.account = {
            "address": "sender@example.test",
            "imap_user": "sender@example.test",
            "imap_password": "secret",
            "imap_host": "imap.example.test",
        }

    def _smtp(self):
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.__exit__.return_value = False
        return smtp

    def test_fallback_key_is_stable_under_whitespace_and_case(self):
        first = email_client._fallback_idempotency_key(
            from_address="Sender@Example.test",
            to_addr="User@Example.test ",
            subject="Hello   world",
            body="same\n body",
        )
        second = email_client._fallback_idempotency_key(
            from_address="sender@example.test",
            to_addr="user@example.test",
            subject="Hello world",
            body="same body",
        )
        self.assertEqual(first, second)

    def test_exact_duplicate_is_suppressed_without_second_smtp_send(self):
        smtp = self._smtp()
        with (
            patch.object(email_client.mongo_store, "get_db", return_value=self.db),
            patch.object(email_client, "_pick_send_account", return_value=self.account),
            patch.object(email_client.smtplib, "SMTP", return_value=smtp),
        ):
            first = email_client.send_email(to_addr="user@example.test", subject="Same", body="Body")
            second = email_client.send_email(to_addr="user@example.test", subject="Same", body="Body")
        self.assertTrue(first["ok"])
        self.assertFalse(first["deduplicated"])
        self.assertTrue(second["ok"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(smtp.sendmail.call_count, 1)

    def test_explicit_key_suppresses_changed_body(self):
        smtp = self._smtp()
        with (
            patch.object(email_client.mongo_store, "get_db", return_value=self.db),
            patch.object(email_client, "_pick_send_account", return_value=self.account),
            patch.object(email_client.smtplib, "SMTP", return_value=smtp),
        ):
            first = email_client.send_email(
                to_addr="user@example.test", subject="Ticket", body="v1", idempotency_key="ticket:one"
            )
            second = email_client.send_email(
                to_addr="user@example.test", subject="Ticket", body="v2", idempotency_key="ticket:one"
            )
        self.assertTrue(first["ok"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(smtp.sendmail.call_count, 1)

    def test_failed_delivery_is_retryable(self):
        failing = self._smtp()
        failing.sendmail.side_effect = RuntimeError("smtp down")
        succeeding = self._smtp()
        with (
            patch.object(email_client.mongo_store, "get_db", return_value=self.db),
            patch.object(email_client, "_pick_send_account", return_value=self.account),
            patch.object(email_client.smtplib, "SMTP", side_effect=[failing, succeeding]),
        ):
            first = email_client.send_email(
                to_addr="user@example.test", subject="Retry", body="Body", idempotency_key="retry:key"
            )
            second = email_client.send_email(
                to_addr="user@example.test", subject="Retry", body="Body", idempotency_key="retry:key"
            )
        self.assertFalse(first["ok"])
        self.assertTrue(second["ok"])
        self.assertFalse(second["deduplicated"])
        self.assertEqual(self.db.email_outbound_ledger.docs["retry:key"]["status"], "sent")

    def test_expired_sent_delivery_can_send_again(self):
        key = "expired:key"
        self.db.email_outbound_ledger.docs[key] = {
            "_id": key,
            "status": "sent",
            "attempts": 1,
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        smtp = self._smtp()
        with (
            patch.object(email_client.mongo_store, "get_db", return_value=self.db),
            patch.object(email_client, "_pick_send_account", return_value=self.account),
            patch.object(email_client.smtplib, "SMTP", return_value=smtp),
        ):
            result = email_client.send_email(
                to_addr="user@example.test", subject="Again", body="Body", idempotency_key=key
            )
        self.assertTrue(result["ok"])
        self.assertFalse(result["deduplicated"])
        self.assertEqual(smtp.sendmail.call_count, 1)

    def test_active_reservation_short_circuits_before_atomic_update(self):
        key = "race:key"
        self.db.email_outbound_ledger.docs[key] = {
            "_id": key,
            "status": "reserved",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
        }
        with patch.object(email_client.mongo_store, "get_db", return_value=self.db):
            reserved, ledger = email_client._reserve_delivery(
                key=key,
                from_address="sender@example.test",
                to_addr="user@example.test",
                subject="Race",
                window_seconds=60,
            )
        self.assertFalse(reserved)
        self.assertEqual(ledger["status"], "reserved")

    def test_duplicate_key_race_is_treated_as_deduplicated(self):
        collection = MagicMock()
        collection.find_one.side_effect = [None, {"_id": "race:key", "status": "reserved"}]
        collection.find_one_and_update.side_effect = DuplicateKeyError("race")
        db = MagicMock()
        db.__getitem__.return_value = collection
        with patch.object(email_client.mongo_store, "get_db", return_value=db):
            reserved, ledger = email_client._reserve_delivery(
                key="race:key",
                from_address="sender@example.test",
                to_addr="user@example.test",
                subject="Race",
                window_seconds=60,
            )
        self.assertFalse(reserved)
        self.assertEqual(ledger["status"], "reserved")

    def test_send_general_email_exposes_and_forwards_idempotency_controls(self):
        path = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "mcp_server.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "send_general_email")
        arg_names = {arg.arg for arg in function.args.args}
        self.assertIn("idempotency_key", arg_names)
        self.assertIn("dedupe_window_seconds", arg_names)
        call = next(node for node in ast.walk(function) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "send_email")
        forwarded = {kw.arg for kw in call.keywords}
        self.assertIn("idempotency_key", forwarded)
        self.assertIn("dedupe_window_seconds", forwarded)


if __name__ == "__main__":
    unittest.main()
