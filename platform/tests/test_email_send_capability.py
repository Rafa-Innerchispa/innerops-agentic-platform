from __future__ import annotations

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


def test_pcdoctor_smtp_defaults_ssl_465():
    smtp = email_client.smtp_settings_for_account(
        {"address": "rlopez@pcdoctor.com.ec", "imap_host": "mail.pcdoctor.com.ec"}
    )
    assert smtp["smtp_host"] == "mail.pcdoctor.com.ec"
    assert smtp["smtp_port"] == 465
    assert smtp["use_ssl"] is True
