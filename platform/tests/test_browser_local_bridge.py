from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import HTTPException

PLATFORM = Path(__file__).resolve().parents[1]
PLATFORM_TEXT = str(PLATFORM)
sys.path[:] = [item for item in sys.path if item != PLATFORM_TEXT]
sys.path.insert(0, PLATFORM_TEXT)

for prefix in ("raphiia_openai", "inneros_core_runtime"):
    for module_name in [name for name in sys.modules if name == prefix or name.startswith(prefix + ".")]:
        sys.modules.pop(module_name, None)

from inneros_core_runtime import browser_session_routes as routes


def _request(host: str):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def test_routes_import_from_current_worktree():
    assert Path(routes.__file__).resolve().is_relative_to(PLATFORM)


def test_local_bridge_disabled_by_default():
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop(routes._LOCAL_AUTOMATION_ENV, None)
        with pytest.raises(HTTPException) as exc:
            routes._require_local_automation(_request("127.0.0.1"))
    assert exc.value.status_code == 404


def test_local_bridge_rejects_non_loopback():
    with mock.patch.dict(os.environ, {routes._LOCAL_AUTOMATION_ENV: "1"}):
        with pytest.raises(HTTPException) as exc:
            routes._require_local_automation(_request("192.168.1.2"))
    assert exc.value.status_code == 403


def test_local_bridge_accepts_loopback_when_enabled():
    with mock.patch.dict(os.environ, {routes._LOCAL_AUTOMATION_ENV: "true"}):
        routes._require_local_automation(_request("127.0.0.1"))
        routes._require_local_automation(_request("::1"))


def test_local_action_does_not_accept_raw_secret_write():
    with pytest.raises(HTTPException) as exc:
        routes._local_action_payload("vault_store_value", category="alpaca", key="password")
    assert exc.value.status_code == 400


def test_vault_fill_requires_only_reference_and_selector():
    payload = routes._local_action_payload(
        "fill_from_vault",
        selector="input[type=password]",
        category="alpaca",
        key="paper_password",
    )
    assert payload == {
        "selector": "input[type=password]",
        "category": "alpaca",
        "key": "paper_password",
    }


def test_local_result_redacts_totp_seed_and_known_tokens():
    seed = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
    token = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    result = routes._sanitize_local_result({"items": [{"text": seed}], "trace": token})
    assert seed not in repr(result)
    assert token not in repr(result)
    assert result["items"][0]["text"] == "[REDACTED_TOTP_SEED]"
    assert result["trace"] == "[REDACTED_TOKEN]"


def test_local_vault_refs_is_metadata_only(monkeypatch):
    import raphiia_openai

    class FakeVault:
        @staticmethod
        def list_owner_credentials(*, category="", reveal=False, actor="RAFAEL"):
            assert category == "alpaca"
            assert reveal is False
            assert actor == "RAFAEL"
            return {"ok": True, "count": 1, "items": [{"key": "paper_email", "category": "alpaca"}]}

    monkeypatch.setattr(raphiia_openai, "owner_vault", FakeVault(), raising=False)
    with mock.patch.dict(os.environ, {routes._LOCAL_AUTOMATION_ENV: "1"}):
        result = routes.local_vault_refs(_request("127.0.0.1"), "alpaca")
    assert result["ok"] is True
    assert result["items"][0]["key"] == "paper_email"
    assert "secret" not in repr(result).lower()
