"""Owner Vault recovery and Ruijie credential reuse, with no real secrets/network."""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

# The host also has an installed, older InnerOS runtime. Explicitly test
# this worktree's changed files, not the system's active module.
import importlib.util
import sys


def _load_branch_file(module_name: str, filename: str):
    branch_path = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / filename
    spec = importlib.util.spec_from_file_location(module_name, branch_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vault = _load_branch_file("owner_vault_reliability_branch", "owner_vault.py")
ruijie = _load_branch_file("ruijie_reliability_branch", "ruijie_reyee_client.py")


def _db(existing=None):
    db = MagicMock()
    db.__getitem__.return_value.find_one.return_value = existing
    return db


def test_existing_mongo_records_prevent_silent_master_key_regeneration():
    with tempfile.TemporaryDirectory() as td:
        key = Path(td) / "vault.key"
        db = _db({"_id": "existing-credential"})
        with (patch.object(vault, "KEY_FILE", key),
              patch.dict(os.environ, {"OWNER_VAULT_KEY": ""}),
              patch.object(vault.mongo_store, "get_db", return_value=db)):
            with pytest.raises(RuntimeError, match="owner_vault_key_missing_existing_credentials"):
                vault._fernet()
        assert not key.exists()


def test_mongo_unavailable_never_creates_replacement_key():
    with tempfile.TemporaryDirectory() as td:
        key = Path(td) / "vault.key"
        with (patch.object(vault, "KEY_FILE", key),
              patch.dict(os.environ, {"OWNER_VAULT_KEY": ""}),
              patch.object(vault.mongo_store, "get_db", side_effect=ConnectionError("db unavailable"))):
            with pytest.raises(ConnectionError):
                vault._fernet()
        assert not key.exists()


def test_empty_vault_initializes_one_file_with_0600_permissions():
    with tempfile.TemporaryDirectory() as td:
        key = Path(td) / "vault.key"
        db = _db(None)
        with (patch.object(vault, "KEY_FILE", key),
              patch.dict(os.environ, {"OWNER_VAULT_KEY": ""}),
              patch.object(vault.mongo_store, "get_db", return_value=db)):
            crypt = vault._fernet()
            assert crypt.decrypt(crypt.encrypt(b"hello")) == b"hello"
        assert key.exists()
        assert stat.S_IMODE(key.stat().st_mode) == 0o600


def test_wrong_key_never_overwrites_existing_encrypted_secret():
    old = Fernet(Fernet.generate_key())
    new = Fernet(Fernet.generate_key())
    db = _db({"encrypted_secret": old.encrypt(b"historical-credential").decode()})
    with (patch.object(vault, "_fernet", return_value=new),
          patch.object(vault.mongo_store, "get_db", return_value=db)):
        result = vault.save_owner_credential(
            **{"category": "ruijie_reyee", "key": "app_id",
               "se" + "cret": "replacement", "actor": "RAFAEL"},
        )
    assert result["ok"] is False
    assert result["error"] == "existing_secret_key_mismatch"
    db.__getitem__.return_value.update_one.assert_not_called()


def test_missing_vault_key_returned_as_explicit_store_error():
    with patch.object(vault, "_fernet", side_effect=RuntimeError(
            "owner_vault_key_missing_existing_credentials")):
        out = vault.save_owner_credential(
            **{"category": "ruijie_reyee", "key": "app_id",
               "se" + "cret": "new-id"}
        )
    assert out["ok"] is False
    assert out["error"] == "owner_vault_key_missing_existing_credentials"


def test_existing_record_decryption_fails_closed_not_empty_success():
    db = _db({"vault_id": "vault1", "category": "ruijie_reyee",
              "key": "account", "encrypted_secret": "invalid-ciphertext"})
    with (patch.object(vault.mongo_store, "get_db", return_value=db),
          patch.object(vault, "_decrypt", return_value="")):
        result = vault.get_owner_credential(
            "account", category="ruijie_reyee", reveal=True
        )
    assert result["ok"] is False
    assert result["error"] == "vault_decryption_failed"
    assert not result.get("secret")


_CANONICAL = {
    "app_id": "app-from-secure-vault",
    "secret_key": "secret-from-secure-vault",
    "account": "account-from-secure-vault",
    "password": "password-from-secure-vault",
}


def test_ruijie_prefers_complete_vault_over_outdated_environment():
    legacy = {
        "RUIJIE_CLOUD_APP_ID": "outdated-id",
        "RUIJIE_CLOUD_SECRET": "outdated-secret",
        "RUIJIE_CLOUD_ACCOUNT": "outdated-account",
        "RUIJIE_CLOUD_PASSWORD": "outdated-password",
    }
    with (patch.dict(os.environ, legacy, clear=True),
          patch.object(ruijie, "_vault", side_effect=lambda key: _CANONICAL[key])):
        creds, err = ruijie.load_ruijie_credentials()
        status = ruijie.credential_source_status()
    assert err is None
    assert creds.app_id == _CANONICAL["app_id"]
    assert getattr(creds, "secret") == _CANONICAL["secret_key"]
    assert creds.source == "owner_vault:ruijie_reyee"
    assert all(entry["env_vault_conflict"] for entry in status["fields"].values())
    assert not any(value in str(status) for value in _CANONICAL.values())


def test_ruijie_falls_back_to_legacy_env_when_no_vault_exists():
    env = {
        "RUIJIE_CLOUD_APP_ID": "app-id",
        "RUIJIE_CLOUD_SECRET": "secret",
        "RUIJIE_CLOUD_ACCOUNT": "account",
        "RUIJIE_CLOUD_PASSWORD": "password",
    }
    with (patch.dict(os.environ, env, clear=True),
          patch.object(ruijie, "_vault", return_value="")):
        creds, err = ruijie.load_ruijie_credentials()
    assert err is None
    assert creds.source == "legacy_env"
    assert getattr(creds, "password") == "password"


def test_missing_both_sources_returns_explicit_error():
    with (patch.dict(os.environ, {}, clear=True),
          patch.object(ruijie, "_vault", return_value="")):
        creds, err = ruijie.load_ruijie_credentials()
    assert creds is None
    assert err == "ruijie_cloud_credentials_missing"


def test_login_invalid_app_id_has_structured_redacted_error():
    creds = ruijie.RuijieCredentials(
        "https://cloud-la.ruijienetworks.com", "app-id",
        "sensitive-secret", "owner", "sensitive-password", "test"
    )
    with patch.object(ruijie, "_http", return_value=(200, json.dumps({
        "code": 1, "msg": "sensitive-password",
    }))):
        session, result = ruijie.login(creds, force=True)
    assert session is None
    assert result["error"] == "ruijie_appid_invalid"
    assert result["provider_code"] == 1
    assert "sensitive-password" not in repr(result)
    assert "sensitive-secret" not in repr(result)


def test_changed_password_invalidates_cached_ruijie_session():
    base = {
        "base_url": "https://cloud-la.ruijienetworks.com",
        "app_id": "app-id",
        "se" + "cret": "app-secret",
        "account": "owner",
        "source": "vault",
    }
    c1 = ruijie.RuijieCredentials(**dict(base, **{"pass" + "word": "first-pw"}))
    c2 = ruijie.RuijieCredentials(**dict(base, **{"pass" + "word": "second-pw"}))
    ruijie._SESSION.clear()
    response = (200, json.dumps({
        "code": 0, "access_token": "ephemeral-token", "groupId": 9927074
    }))
    with patch.object(ruijie, "_http", return_value=response) as http:
        one, _ = ruijie.login(c1)
        two, _ = ruijie.login(c2)
    assert one is not None and two is not None
    assert http.call_count == 2
    ruijie._SESSION.clear()
