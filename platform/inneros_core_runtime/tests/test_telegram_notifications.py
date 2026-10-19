"""Unit tests for Telegram notifications parallel channel and fallback."""

from unittest.mock import MagicMock, patch
from inneros_core_runtime.notifications import telegram_client


def test_telegram_unconfigured_safe_skip(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    st = telegram_client.telegram_status()
    assert st["ok"] is False
    assert st["configured"] is False
    assert st["action_required"] is not None

    res = telegram_client.send_telegram_message("Test message")
    assert res["ok"] is False
    assert res["skipped"] is True
    assert res["reason"] == "credentials_not_configured"


def test_telegram_configured_send_mock(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mock_bot_123456:ABC-DEF")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")

    st = telegram_client.telegram_status()
    assert st["ok"] is True
    assert st["configured"] is True
    assert st["chat_id_hint"] == "...4321"

    fake_resp = MagicMock()
    fake_resp.read.return_value = b'{"ok": true, "result": {"message_id": 42}}'
    fake_resp.__enter__.return_value = fake_resp

    with patch("urllib.request.urlopen", return_value=fake_resp):
        res = telegram_client.send_telegram_message("Alerta de prueba")
        assert res["ok"] is True
        assert res["message_id"] == 42
        assert res["channel"] == "telegram"


def test_no_secret_leak_in_error_logs(monkeypatch):
    token = "secret_bot_token_99999"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    with patch("urllib.request.urlopen", side_effect=Exception(f"Connection failed to https://api.telegram.org/bot{token}/sendMessage")):
        res = telegram_client.send_telegram_message("Alerta")
        assert res["ok"] is False
        assert token not in res["error"]
        assert "[REDACTED_TELEGRAM_TOKEN]" in res["error"]


def test_send_alert_whatsapp_dual_delivery(monkeypatch):
    from inneros_core_runtime.notifications import evolution_client

    monkeypatch.setattr(evolution_client, "send_whatsapp", lambda body, number=None, node=None: {"ok": True, "id": "wa_123"})
    fake_tg = {"ok": True, "message_id": 999, "channel": "telegram"}
    monkeypatch.setattr("inneros_core_runtime.notifications.telegram_client.send_alert_telegram", lambda body: fake_tg)

    res = evolution_client.send_alert_whatsapp("Alerta dual")
    assert res["ok"] is True
    assert res.get("id") == "wa_123"
    assert res.get("telegram", {}).get("ok") is True


def test_send_alert_whatsapp_telegram_fallback(monkeypatch):
    from inneros_core_runtime.notifications import evolution_client

    # WhatsApp fails (e.g. session down)
    monkeypatch.setattr(evolution_client, "send_whatsapp", lambda body, number=None, node=None: {"ok": False, "error": "session_closed"})
    # Telegram succeeds
    fake_tg = {"ok": True, "message_id": 1000, "channel": "telegram"}
    monkeypatch.setattr("inneros_core_runtime.notifications.telegram_client.send_alert_telegram", lambda body: fake_tg)

    res = evolution_client.send_alert_whatsapp("Alerta con WhatsApp caido")
    assert res["ok"] is True
    assert res.get("fallback_channel") == "telegram"
    assert res.get("telegram", {}).get("message_id") == 1000
