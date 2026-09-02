
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime import owner_vault, owner_vault_bridge
from raphiia_openai import mongo_store
from raphiia_openai.mcp_catalog import tool_catalog
from raphiia_openai import mcp_profiles


class FakeCursor(list):
    def sort(self, *_args, **_kwargs):
        return self


class FakeCollection:
    def __init__(self):
        self.docs = {}

    def update_one(self, filt, update, upsert=False):
        vault_id = update.get("$set", {}).get("vault_id") or filt.get("vault_id")
        doc = dict(self.docs.get(vault_id, {}))
        doc.update(update.get("$setOnInsert", {}))
        doc.update(update.get("$set", {}))
        self.docs[vault_id] = doc
        return type("Result", (), {"modified_count": 1, "upserted_id": vault_id})()

    def find_one(self, filt, projection=None):
        for doc in self.docs.values():
            if all(doc.get(k) == v for k, v in filt.items()):
                return {k: v for k, v in doc.items() if k != "_id"}
        return None

    def find(self, filt, projection=None):
        rows = []
        for doc in self.docs.values():
            if all(doc.get(k) == v for k, v in filt.items()):
                rows.append({k: v for k, v in doc.items() if k != "_id"})
        return FakeCursor(rows)


class FakeDB(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


def _setup_vault(monkeypatch, tmp_path):
    db = FakeDB()
    monkeypatch.setattr(mongo_store, "get_db", lambda: db)
    monkeypatch.setattr(owner_vault, "KEY_FILE", tmp_path / "vault.key")
    monkeypatch.setenv("HOME", str(tmp_path))
    return db


def test_store_status_and_materialize_never_return_plaintext(monkeypatch, tmp_path):
    _setup_vault(monkeypatch, tmp_path)
    secret = "super-secret-token"

    stored = owner_vault_bridge.store_secret(
        category="cloudflare",
        key="worker_deploy",
        secret=secret,
        label="Worker deploy",
        project_id="inneros-webmcp",
    )

    assert stored["ok"] is True
    assert stored["secret_returned"] is False
    assert stored["secret_ref"] == "owner_vault:cloudflare/worker_deploy"
    assert secret not in repr(stored)

    status_out = owner_vault_bridge.secret_status(category="cloudflare", key="worker_deploy")
    assert status_out["ok"] is True
    assert status_out["present"] is True
    assert status_out["secret_returned"] is False
    assert status_out["metadata"]["project_id"] == "inneros-webmcp"
    assert secret not in repr(status_out)

    env = owner_vault_bridge.materialize_project_env(
        namespace="inneros-webmcp",
        bindings={"CLOUDFLARE_API_TOKEN": "owner_vault:cloudflare/worker_deploy"},
        static_values={"CLOUDFLARE_ACCOUNT_ID": "account_123"},
    )
    assert env["ok"] is True
    assert env["secret_returned"] is False
    assert env["mode"] == "0600"
    assert secret not in repr(env)
    path = Path(env["path"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text().splitlines() == [
        "CLOUDFLARE_API_TOKEN=super-secret-token",
        "CLOUDFLARE_ACCOUNT_ID=account_123",
    ]


def test_owner_only_and_invalid_inputs_are_blocked(monkeypatch, tmp_path):
    _setup_vault(monkeypatch, tmp_path)

    assert owner_vault_bridge.store_secret(category="cloud", key="k", secret="s", actor="CHATGPT")["error"] == "owner_only"
    with pytest.raises(ValueError):
        owner_vault_bridge.store_secret(category="../cloud", key="k", secret="s")
    bad_ref = owner_vault_bridge.materialize_project_env(namespace="demo", bindings={"TOKEN": "plain-secret"})
    assert bad_ref["ok"] is False
    assert bad_ref["error"] == "invalid_secret_ref"
    bad_env = owner_vault_bridge.materialize_project_env(namespace="demo", bindings={"bad-token": "owner_vault:x/y"})
    assert bad_env["ok"] is False
    assert bad_env["error"] == "invalid_env_name"


def test_mcp_catalog_and_profiles_expose_owner_vault_tools():
    expected = {
        "owner_vault_store_secret",
        "owner_vault_secret_status",
        "owner_vault_materialize_project_env",
    }
    assert expected.issubset(set(tool_catalog.ALL_MCP_TOOL_NAMES))
    for name in expected:
        meta = tool_catalog.describe_tool(name)
        assert meta["ok"] is True
        assert meta["risk_level"] in {"medium", "high"}
    profile = mcp_profiles.PROFILES["owner_vault"]
    assert expected.issubset(set(profile["tools"]))
    assert mcp_profiles.validate_profiles()["ok"] is True
