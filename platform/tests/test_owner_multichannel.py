"""Mocked transport contract. This test never sends network messages."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import sys
from unittest.mock import Mock

import pytest

path = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "notifications" / "owner_multichannel.py"
spec = importlib.util.spec_from_file_location("owner_multichannel_test_module", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def example(**updates):
    opts = {
        "task_id": "ops_abcdef123456",
        "title": "Verificar limpieza temporal",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "risk": "high",
    }
    opts.update(updates)
    return module.OwnerApprovalNotice(**opts)


def test_links_have_intent_but_never_grant_authority():
    urls = module.approval_links(example(), "https://approve.example.org")
    assert urls["approve"].endswith("?intent=approve")
    assert urls["reject"].endswith("?intent=reject")
    assert urls["review"].endswith("/ops_abcdef123456")


@pytest.mark.parametrize("origin", [
    "http://approve.example.org",
    "https://user:pass@approve.example.org",
    "https://approve.example.org/path",
    "https://approve.example.org?arg=value",
    "https://approve.example.org#section",
])
def test_reject_bad_approval_origins(origin):
    with pytest.raises(ValueError):
        module.approval_links(example(), origin)


@pytest.mark.parametrize("task_id", ["bad", "ops_zzzzzzzzzzzz", "ops_123", "ops_abcdef123456/path"])
def test_bad_ids_rejected(task_id):
    with pytest.raises(ValueError):
        module.approval_links(example(task_id=task_id), "https://approve.example.org")


def test_expired_rejected():
    with pytest.raises(ValueError):
        module.ntfy_payload(example(expires_at=datetime.now(timezone.utc) - timedelta(seconds=5)),
                            topic="ownerprivate", approval_origin="https://approve.example.org")


def test_ntfy_actions_are_view_only():
    data = module.ntfy_payload(example(), topic="ownerprivate",
                               approval_origin="https://approve.example.org")
    assert data["priority"] == 5
    assert [a["action"] for a in data["actions"]] == ["view", "view"]
    assert [a["label"] for a in data["actions"]] == ["Aprobar", "Rechazar"]


def test_telegram_actions_are_links_not_callbacks():
    data = module.telegram_payload(example(), chat_id="123456789",
                                   approval_origin="https://approve.example.org")
    buttons = data["reply_markup"]["inline_keyboard"][0]
    assert all("url" in a and "callback_data" not in a for a in buttons)


def test_ntfy_sender_receipt():
    response = Mock(status_code=200)
    response.json.return_value = {"id": "msg123"}
    post = Mock(return_value=response)
    out = module.send_ntfy(example(), server_origin="https://notify.example.org",
                           topic="ownerprivate", approval_origin="https://approve.example.org",
                           access_token="opaque", post=post)
    assert out["ok"] is True
    assert out["provider_message_id"] == "msg123"
    assert out["delivery"] == "provider_accepted"
    assert post.call_args.kwargs["timeout"] == 8


def test_ntfy_rejection_not_accepted():
    post = Mock(return_value=Mock(status_code=503))
    out = module.send_ntfy(example(), server_origin="https://notify.example.org",
                           topic="ownerprivate", approval_origin="https://approve.example.org",
                           access_token="opaque", post=post)
    assert out["ok"] is False


def test_telegram_sender_receipt():
    response = Mock(status_code=200)
    response.json.return_value = {"ok": True, "result": {"message_id": 123}}
    out = module.send_telegram(example(), chat_id="123456789", bot_token="opaque",
                               approval_origin="https://approve.example.org",
                               post=Mock(return_value=response))
    assert out["provider_message_id"] == "123"
    assert out["delivery"] == "provider_accepted"


def test_telegram_failure_is_safe():
    out = module.send_telegram(example(), chat_id="123456789", bot_token="opaque",
                               approval_origin="https://approve.example.org",
                               post=Mock(side_effect=RuntimeError("private")))
    assert out["ok"] is False
    assert "private" not in str(out)
