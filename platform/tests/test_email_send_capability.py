from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from inneros_core_runtime import capability_gateway
from inneros_core_runtime.notifications import email_client


def test_email_send_capability_registered():
    desc = capability_gateway.capability_describe("email.send.v1")
    assert desc["ok"] is True
    assert desc["capability"]["domain"] == "communications"


def test_email_identities_list_capability():
    db = MagicMock()
    db.email_accounts.find.return_value = [
        {
            "address": "rlopez@pcdoctor.com.ec",
            "enabled": True,
            "label": "Rafa",
            "imap_host": "mail.pcdoctor.com.ec",
        }
    ]
    with patch.object(email_client.mongo_store, "get_db", return_value=db):
        result = capability_gateway.capability_invoke("email.identities.list.v1", {})
    assert result["ok"] is True
    ids = [item["from_identity"] for item in result["result"]["identities"]]
    assert "rlopez@pcdoctor.com.ec" in ids


def test_email_sent_query_capability_registered():
    desc = capability_gateway.capability_describe("email.sent.query.v1")
    assert desc["ok"] is True
    assert desc["capability"]["domain"] == "communications"
    assert desc["capability"]["mode"] == "read_only"


def test_pcdoctor_smtp_defaults_ssl_465():
    smtp = email_client.smtp_settings_for_account(
        {"address": "rlopez@pcdoctor.com.ec", "imap_host": "mail.pcdoctor.com.ec"}
    )
    assert smtp["smtp_host"] == "mail.pcdoctor.com.ec"
    assert smtp["smtp_port"] == 465
    assert smtp["use_ssl"] is True


def test_discover_sent_folder_special_use():
    client = MagicMock()
    client.list.return_value = (
        "OK",
        [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren \\Drafts) "/" "Drafts"',
            b'(\\HasNoChildren \\Sent) "/" "INBOX.Sent"',
            b'(\\HasNoChildren \\Trash) "/" "Trash"',
        ],
    )
    folder = email_client.discover_sent_folder(client)
    assert folder == "INBOX.Sent"


def test_discover_sent_folder_fallback_name():
    client = MagicMock()
    client.list.return_value = (
        "OK",
        [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Sent Items"',
            b'(\\HasNoChildren) "/" "Trash"',
        ],
    )
    folder = email_client.discover_sent_folder(client)
    assert folder == "Sent Items"


def test_send_email_smtp_and_imap_success():
    account_doc = {
        "address": "rlopez@pcdoctor.com.ec",
        "imap_user": "rlopez@pcdoctor.com.ec",
        "imap_password": "secret_password",
        "imap_host": "mail.pcdoctor.com.ec",
        "imap_port": 993,
        "smtp_host": "mail.pcdoctor.com.ec",
        "smtp_port": 465,
        "enabled": True,
        "send_enabled": True,
    }
    db = MagicMock()
    db.email_accounts.find_one.return_value = account_doc
    db.email_outbound_ledger.find_one.return_value = None
    db.email_outbound_ledger.find_one_and_update.return_value = {
        "_id": "email:test_key_1",
        "status": "reserved",
    }

    mock_smtp_instance = MagicMock()
    mock_smtp_cls = MagicMock(return_value=mock_smtp_instance)
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance

    mock_imap_instance = MagicMock()
    mock_imap_cls = MagicMock(return_value=mock_imap_instance)
    mock_imap_instance.list.return_value = ("OK", [b'(\\Sent) "/" "Sent"'])
    mock_imap_instance.append.return_value = ("OK", [b"[APPENDUID 12345 678]"])

    with (
        patch.object(email_client.mongo_store, "get_db", return_value=db),
        patch("smtplib.SMTP_SSL", mock_smtp_cls),
        patch("imaplib.IMAP4_SSL", mock_imap_cls),
    ):
        result = email_client.send_email(
            to_addr="destinatario@test.com",
            subject="Test Subject Live",
            body="Hello from InnerOS test.",
            from_account="rlopez@pcdoctor.com.ec",
            idempotency_key="test_send_success_key",
        )

    assert result["ok"] is True
    assert result["smtp_accepted"] is True
    assert result["sent_folder"] == "Sent"
    assert result["append_status"] == "appended"
    assert "message_id" in result
    assert result["message_id"].endswith("@pcdoctor.com.ec>")

    # Verify SMTP was called with bytes and correct recipients
    assert mock_smtp_instance.sendmail.called
    args, _ = mock_smtp_instance.sendmail.call_args
    assert args[0] == "rlopez@pcdoctor.com.ec"
    assert args[1] == ["destinatario@test.com"]
    assert isinstance(args[2], bytes)

    # Verify IMAP append was called
    assert mock_imap_instance.append.called
    app_args, _ = mock_imap_instance.append.call_args
    assert app_args[0] == "Sent"


def test_send_email_smtp_ok_imap_fail_no_resend():
    account_doc = {
        "address": "info@pcdoctor.com.ec",
        "imap_user": "info@pcdoctor.com.ec",
        "imap_password": "secret_password",
        "imap_host": "mail.pcdoctor.com.ec",
        "imap_port": 993,
        "smtp_host": "mail.pcdoctor.com.ec",
        "smtp_port": 465,
        "enabled": True,
        "send_enabled": True,
    }
    db = MagicMock()
    db.email_accounts.find_one.return_value = account_doc
    db.email_outbound_ledger.find_one.return_value = None
    db.email_outbound_ledger.find_one_and_update.return_value = {
        "_id": "email:test_key_2",
        "status": "reserved",
    }

    mock_smtp_instance = MagicMock()
    mock_smtp_cls = MagicMock(return_value=mock_smtp_instance)
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance

    # IMAP fails during append
    mock_imap_instance = MagicMock()
    mock_imap_cls = MagicMock(return_value=mock_imap_instance)
    mock_imap_instance.list.return_value = ("OK", [b'(\\Sent) "/" "Sent"'])
    mock_imap_instance.append.side_effect = Exception("IMAP storage quota full or connection dropped")

    with (
        patch.object(email_client.mongo_store, "get_db", return_value=db),
        patch("smtplib.SMTP_SSL", mock_smtp_cls),
        patch("imaplib.IMAP4_SSL", mock_imap_cls),
    ):
        result = email_client.send_email(
            to_addr="destinatario@test.com",
            subject="Test IMAP Failure Mode",
            body="Message sent via SMTP but IMAP append failed.",
            from_account="info@pcdoctor.com.ec",
            idempotency_key="test_send_imap_fail_key",
        )

    # Crucial: delivery was accepted by SMTP so ok=True, but append_status is 'failed'
    assert result["ok"] is True
    assert result["smtp_accepted"] is True
    assert result["append_status"] == "failed"


def test_send_email_unauthorized_identity_rejected():
    account_doc = {
        "address": "hacker@evil.com",
        "enabled": True,
    }
    db = MagicMock()
    db.email_accounts.find_one.return_value = account_doc

    with patch.object(email_client.mongo_store, "get_db", return_value=db):
        result = email_client.send_email(
            to_addr="victim@test.com",
            subject="Spam",
            body="Evil",
            from_account="hacker@evil.com",
        )

    assert result["ok"] is False
    assert result["error"] == "from_identity_not_allowlisted"


def test_query_sent_emails_filters():
    now = datetime.datetime.now(datetime.timezone.utc)
    mock_docs = [
        {
            "_id": "exec_654a885da712",
            "from_address": "rlopez@pcdoctor.com.ec",
            "to_addr": "mmontufa@pacifico.fin.ec",
            "subject": "Solicitud de certificado de saldos promedios",
            "message_id": "<123@pcdoctor.com.ec>",
            "smtp_accepted_at": now,
            "sent_folder": "INBOX.Sent",
            "append_status": "appended",
            "body_hash": "abc123hash",
            "status": "sent",
        }
    ]
    db = MagicMock()
    cursor_mock = MagicMock()
    cursor_mock.sort.return_value = cursor_mock
    cursor_mock.limit.return_value = mock_docs
    db[email_client.OUTBOUND_LEDGER_COLLECTION].find.return_value = cursor_mock

    with patch.object(email_client.mongo_store, "get_db", return_value=db):
        result = capability_gateway.capability_invoke(
            "email.sent.query.v1",
            {"from_identity": "rlopez@pcdoctor.com.ec", "limit": 10},
        )

    assert result["ok"] is True
    assert result["result"]["count"] == 1
    rec = result["result"]["records"][0]
    assert rec["execution_id"] == "exec_654a885da712"
    assert rec["to"] == "mmontufa@pacifico.fin.ec"
    assert rec["append_status"] == "appended"
    assert rec["sent_folder"] == "INBOX.Sent"
    assert "password" not in str(rec)
