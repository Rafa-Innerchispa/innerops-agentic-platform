from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime import boson_provider, resource_fabric


def test_manifest_is_global_voice_provider_without_secret() -> None:
    manifest = boson_provider.manifest_document()
    assert manifest["id"] == "boson-higgs"
    assert "voice_agent_session" in manifest["capabilities"]
    assert "realtime_s2s" in manifest["capabilities"]
    assert manifest["auth_mode"] == "owner_vault"
    assert "api.boson.ai" in manifest["allowed_domains"]
    assert "bearer " not in repr(manifest).lower()


def test_status_never_reveals_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        boson_provider.owner_vault,
        "get_owner_credential",
        lambda *args, **kwargs: {"ok": True, "vault_id": "cred_boson", "secret": "SHOULD_NOT_APPEAR"},
    )
    status = boson_provider.provider_status()
    assert status["configured"] is True
    assert status["raw_secret_exposed"] is False
    assert "SHOULD_NOT_APPEAR" not in repr(status)
    assert status["credit_governor"] == "AG-54_FUNDING_CREDITS"


def test_store_api_key_returns_reference_not_secret(monkeypatch) -> None:
    captured = {}

    def fake_save(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "vault_id": "cred_voice_ai_provider_boson_api_key"}

    monkeypatch.setattr(boson_provider.owner_vault, "save_owner_credential", fake_save)
    result = boson_provider.store_api_key_server_side("bai-test-secret")
    assert result["ok"] is True
    assert result["raw_secret_exposed"] is False
    assert "bai-test-secret" not in repr(result)
    assert captured["secret"] == "bai-test-secret"


def test_live_preflight_mints_secret_without_returning_it(monkeypatch) -> None:
    monkeypatch.setattr(boson_provider, "_credential_metadata", lambda: {"ok": True})
    monkeypatch.setattr(boson_provider, "_mint_client_secret", lambda *args, **kwargs: "EPHEMERAL")
    result = boson_provider.provider_preflight(live=True)
    assert result["ok"] is True
    assert result["checks"]["realtime_client_secret_mint"] is True
    assert "EPHEMERAL" not in repr(result)


def test_client_secret_is_short_lived_and_permanent_key_is_not_returned(monkeypatch) -> None:
    monkeypatch.setattr(boson_provider, "_mint_client_secret", lambda *args, **kwargs: "EPHEMERAL")
    result = boson_provider.create_realtime_client_secret(90)
    assert result["ok"] is True
    assert result["token"] == "EPHEMERAL"
    assert result["permanent_secret_exposed"] is False
    assert result["model"] == "higgs-realtime"


def test_resource_fabric_includes_boson_global_provider(monkeypatch) -> None:
    monkeypatch.setattr(boson_provider, "_credential_metadata", lambda: {"ok": True})
    result = resource_fabric.bootstrap_global_resource_fabric(dry_run=True)
    providers = {row["provider_id"]: row for row in result["providers"]}
    assert providers["boson-higgs"]["status"] == "active"
    assert "voice_agent_session" in providers["boson-higgs"]["capabilities"]
    assert providers["boson-higgs"]["credit_governor"] == "AG-54_FUNDING_CREDITS"
