from __future__ import annotations

import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
PLATFORM_TEXT = str(PLATFORM)
sys.path[:] = [item for item in sys.path if item != PLATFORM_TEXT]
sys.path.insert(0, PLATFORM_TEXT)

for prefix in ("raphiia_openai", "inneros_core_runtime"):
    cached_names = [name for name in sys.modules if name == prefix or name.startswith(prefix + ".")]
    for module_name in cached_names:
        sys.modules.pop(module_name, None)

import raphiia_openai
from inneros_core_runtime import browser_session_broker as broker


def test_broker_import_is_from_current_worktree():
    assert Path(broker.__file__).resolve().is_relative_to(PLATFORM)


class FakeLocator:
    def __init__(self, page, texts=None):
        self.page = page
        self.texts = list(texts or [])

    @property
    def first(self):
        return self

    def fill(self, value, timeout=10000):
        self.page.filled = value

    def all_inner_texts(self):
        return list(self.texts)


class FakePage:
    url = "https://app.alpaca.markets/test"
    filled = ""

    def __init__(self, button_texts=None):
        self.button_texts = list(button_texts or [])

    def title(self):
        return "Alpaca Test"

    def locator(self, selector):
        return FakeLocator(self, self.button_texts if selector == "button" else [])


class FakeVault:
    def __init__(self, stored_seed=""):
        self.saved = None
        self.stored_seed = stored_seed

    def save_owner_credential(self, *, key, secret, category, label="", metadata=None, actor="RAFAEL"):
        self.saved = {
            "key": key,
            "value": secret,
            "category": category,
            "label": label,
            "metadata": dict(metadata or {}),
            "actor": actor,
        }
        return {"ok": True, "vault_id": "vault-test"}

    def get_owner_credential(self, key, category="general", reveal=False, actor="RAFAEL"):
        return {"ok": True, "secret": self.stored_seed} if reveal else {"ok": True}


def _session(page):
    return broker.BrowserSession(
        session_id="bs_test",
        token="token",
        profile="test",
        start_url=page.url,
        created_at=0,
        expires_at=9999999999,
        page=page,
        status="ready",
    )


def test_vault_store_uses_keyword_only_api_and_never_returns_plaintext(monkeypatch):
    fake_vault = FakeVault()
    monkeypatch.setattr(raphiia_openai, "owner_vault", fake_vault, raising=False)
    page = FakePage()
    result = broker._execute_page_command(
        _session(page),
        "vault_store_value",
        {
            "category": "alpaca",
            "key": "paper_login",
            "value": "do-not-return-this",
            "label": "test",
            "project_id": "inneros-alpha-alpaca",
        },
    )
    assert result["ok"] is True
    assert result["value_returned"] is False
    assert "do-not-return-this" not in repr(result)
    assert fake_vault.saved["value"] == "do-not-return-this"
    assert fake_vault.saved["metadata"]["project_id"] == "inneros-alpha-alpaca"


def test_totp_capture_saves_seed_without_returning_it(monkeypatch):
    seed = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
    fake_vault = FakeVault()
    monkeypatch.setattr(raphiia_openai, "owner_vault", fake_vault, raising=False)
    page = FakePage(["Continue", seed])
    result = broker._execute_page_command(
        _session(page),
        "vault_capture_totp",
        {"category": "alpaca", "key": "totp_seed", "project_id": "inneros-alpha-alpaca"},
    )
    assert result["ok"] is True
    assert result["value_returned"] is False
    assert seed not in repr(result)
    assert fake_vault.saved["value"] == seed


def test_totp_fill_uses_vault_and_does_not_return_code(monkeypatch):
    seed = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
    fake_vault = FakeVault(stored_seed=seed)
    monkeypatch.setattr(raphiia_openai, "owner_vault", fake_vault, raising=False)
    page = FakePage()
    result = broker._execute_page_command(
        _session(page),
        "fill_totp_from_vault",
        {"category": "alpaca", "key": "totp_seed", "selector": "input[name=code]"},
    )
    assert result["ok"] is True
    assert result["code_returned"] is False
    assert len(page.filled) == 6
    assert page.filled.isdigit()
    assert page.filled not in repr(result)


def test_generic_fill_from_vault_never_returns_value(monkeypatch):
    fake_vault = FakeVault(stored_seed="stored-login-value")
    monkeypatch.setattr(raphiia_openai, "owner_vault", fake_vault, raising=False)
    page = FakePage()
    result = broker._execute_page_command(
        _session(page),
        "fill_from_vault",
        {"category": "alpaca", "key": "password", "selector": "input[type=password]"},
    )
    assert result["ok"] is True
    assert result["value_returned"] is False
    assert page.filled == "stored-login-value"
    assert "stored-login-value" not in repr(result)
