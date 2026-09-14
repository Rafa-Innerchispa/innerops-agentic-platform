from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime import provider_onboarding_plane, resource_fabric


def _set_manifest_dir(monkeypatch, root: Path) -> None:
    # The legacy raphiia_openai compatibility shim can load the canonical module
    # under a second module identity. Patch both references so unit tests never
    # read the host's real provider manifests.
    monkeypatch.setattr(provider_onboarding_plane, "MANIFEST_DIR", root)
    monkeypatch.setattr(resource_fabric.provider_onboarding_plane, "MANIFEST_DIR", root)


def _write_manifest(root: Path, provider_id: str, *, capabilities: list[str]) -> None:
    payload = {
        "id": provider_id,
        "label": f"{provider_id} fixture",
        "endpoints": [],
        "cli": "",
        "sdk": "fixture-sdk",
        "auth_mode": "owner_vault",
        "secret_category": "voice_ai_provider",
        "scopes": [],
        "capabilities": ["status", "preflight", "dry_run", "audit", *capabilities],
        "risk_level": "moderate_write",
        "allowed_resources": ["streaming_transcription"],
        "allowed_domains": ["example.test"],
        "rate_limits": {"session_starts_per_minute": 5},
        "common_interface": ["status", "preflight", "dry_run", "apply", "rollback", "audit"],
        "registered_at": "2026-09-14T00:00:00+00:00",
    }
    (root / f"{provider_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_registered_manifest_projects_as_reusable_provider(monkeypatch, tmp_path: Path) -> None:
    _set_manifest_dir(monkeypatch, tmp_path)
    _write_manifest(tmp_path, "speechmatics", capabilities=["realtime_stt", "batch_stt"])

    docs = resource_fabric._registered_manifest_provider_documents()

    assert len(docs) == 1
    speechmatics = docs[0]
    assert speechmatics["provider_id"] == "speechmatics"
    assert speechmatics["kind"] == "external_voice_provider"
    assert speechmatics["status"] == "configured"
    assert speechmatics["auth_mode"] == "owner_vault"
    assert "realtime_stt" in speechmatics["capabilities"]
    assert "status" not in speechmatics["capabilities"]
    rendered = repr(speechmatics).lower()
    assert "api_key" not in rendered
    assert "password" not in rendered


def test_native_provider_wins_when_manifest_id_is_duplicate(monkeypatch, tmp_path: Path) -> None:
    _set_manifest_dir(monkeypatch, tmp_path)
    _write_manifest(tmp_path, "assemblyai", capabilities=["realtime_stt"])

    docs = resource_fabric._registered_manifest_provider_documents({"assemblyai"})

    assert docs == []


def test_bootstrap_dry_run_includes_speechmatics_and_preserves_assemblyai(monkeypatch, tmp_path: Path) -> None:
    _set_manifest_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(
        resource_fabric.funding_registry,
        "get_funding_registry_summary",
        lambda limit=5: {"ok": True, "limit": limit},
    )
    _write_manifest(tmp_path, "speechmatics", capabilities=["realtime_stt"])
    _write_manifest(tmp_path, "assemblyai", capabilities=["realtime_stt"])

    result = resource_fabric.bootstrap_global_resource_fabric(dry_run=True)
    providers = [row for row in result["providers"] if row["provider_id"] in {"speechmatics", "assemblyai"}]
    by_id = {row["provider_id"]: row for row in providers}

    assert set(by_id) == {"speechmatics", "assemblyai"}
    assert sum(1 for row in providers if row["provider_id"] == "assemblyai") == 1
    assert "realtime_stt" in by_id["speechmatics"]["capabilities"]
    assert by_id["assemblyai"]["kind"] == "external_voice_provider"


def test_capability_link_can_target_projected_provider(monkeypatch, tmp_path: Path) -> None:
    _set_manifest_dir(monkeypatch, tmp_path)
    _write_manifest(tmp_path, "speechmatics", capabilities=["realtime_stt"])
    provider = resource_fabric._registered_manifest_provider_documents()[0]
    link = resource_fabric.link_project_capability(
        "inneros-physical-guardian-ai-infra-2026",
        "realtime_stt",
        provider_id="speechmatics",
        task_id="ops_fixture",
        dry_run=True,
    )

    assert link["ok"] is True
    assert link["link"]["provider_id"] == provider["provider_id"]
    assert link["link"]["capability"] in provider["capabilities"]
