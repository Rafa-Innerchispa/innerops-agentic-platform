from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime import assemblyai_provider, provider_onboarding_plane, resource_fabric


def test_manifest_is_reusable_and_contains_no_secret() -> None:
    manifest = assemblyai_provider.manifest_document()
    assert manifest["id"] == "assemblyai"
    assert "voice_agent_session" in manifest["capabilities"]
    assert "session_resume" in manifest["capabilities"]
    assert "pii_redaction" in manifest["capabilities"]
    assert manifest["auth_mode"] == "owner_vault"
    rendered = repr(manifest).lower()
    assert "assemblyai_api_key=" not in rendered
    assert "bearer " not in rendered


def test_provider_status_never_reveals_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        assemblyai_provider.owner_vault,
        "get_owner_credential",
        lambda *args, **kwargs: {"ok": True, "vault_id": "cred_voice", "secret": "SHOULD_NOT_APPEAR"},
    )
    status = assemblyai_provider.provider_status()
    assert status["configured"] is True
    assert status["raw_secret_exposed"] is False
    assert "SHOULD_NOT_APPEAR" not in repr(status)
    assert status["credential_ref"].startswith("owner_vault:")


def test_store_api_key_returns_reference_not_secret(monkeypatch) -> None:
    captured = {}

    def fake_save(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "vault_id": "cred_voice_ai_provider_assemblyai_api_key"}

    monkeypatch.setattr(assemblyai_provider.owner_vault, "save_owner_credential", fake_save)
    result = assemblyai_provider.store_api_key_server_side("TOP-SECRET")
    assert result["ok"] is True
    assert result["vault_id"].startswith("cred_")
    assert "TOP-SECRET" not in repr(result)
    assert captured["secret"] == "TOP-SECRET"


def test_live_preflight_mints_token_without_returning_it(monkeypatch) -> None:
    monkeypatch.setattr(assemblyai_provider, "_credential_metadata", lambda: {"ok": True})
    monkeypatch.setattr(assemblyai_provider, "_mint_temporary_token", lambda *args, **kwargs: "TEMP-TOKEN")
    result = assemblyai_provider.provider_preflight(live=True)
    assert result["ok"] is True
    assert result["checks"]["temporary_token_mint"] is True
    assert "TEMP-TOKEN" not in repr(result)


def test_transcribe_audio_url_sanitizes_input_url_and_returns_guardrail_evidence(monkeypatch) -> None:
    monkeypatch.setattr(assemblyai_provider, "_api_key", lambda: "SECRET")
    responses = iter(
        [
            {"id": "tx_123"},
            {
                "status": "completed",
                "text": "[PERSON_NAME] autoriza revisar Puerta.",
                "confidence": 0.96,
                "entities": [{"entity_type": "location", "text": "Puerta", "start": 28, "end": 34}],
                "content_safety_labels": {"status": "safe"},
            },
        ]
    )
    monkeypatch.setattr(assemblyai_provider, "_json_request", lambda *args, **kwargs: next(responses))
    result = assemblyai_provider.transcribe_audio_url(
        "https://media.example.test/signed-note.ogg?token=PRIVATE",
        keyterms=["Ralphi", "Puerta", "Bellini"],
    )
    assert result["ok"] is True
    assert result["pii_redaction_enabled"] is True
    assert result["audio_url_exposed"] is False
    assert "PRIVATE" not in repr(result)
    assert result["entities"][0]["entity_type"] == "location"


def test_resource_fabric_dry_run_includes_global_assemblyai_provider(monkeypatch) -> None:
    monkeypatch.setattr(assemblyai_provider, "_credential_metadata", lambda: {"ok": False})
    result = resource_fabric.bootstrap_global_resource_fabric(dry_run=True)
    providers = {row["provider_id"]: row for row in result["providers"]}
    assert "assemblyai" in providers
    assert providers["assemblyai"]["kind"] == "external_voice_provider"
    assert "tool_calling" in providers["assemblyai"]["capabilities"]


def test_provider_onboarding_requires_real_scoped_host_approval(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(provider_onboarding_plane, "MANIFEST_DIR", tmp_path)
    monkeypatch.setattr(
        provider_onboarding_plane,
        "_validate_host_approval",
        lambda approval_id: {"ok": approval_id == "hostap_valid", "error": "approval_scope_mismatch"},
    )
    manifest = assemblyai_provider.manifest_document()
    denied = provider_onboarding_plane.provider_register_manifest(manifest, dry_run=False, approval_id="approval_fake123")
    assert denied["ok"] is False
    assert not (tmp_path / "assemblyai.json").exists()

    allowed = provider_onboarding_plane.provider_register_manifest(manifest, dry_run=False, approval_id="hostap_valid")
    assert allowed["ok"] is True
    assert allowed["executed"] is True
    assert (tmp_path / "assemblyai.json").exists()
