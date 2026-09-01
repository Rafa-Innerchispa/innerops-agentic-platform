from types import SimpleNamespace

import pytest

from inneros_core_runtime import editorial_social, linkedin_client


def test_token_diagnostics_reports_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linkedin_client, "_token", lambda: "")
    monkeypatch.setattr(linkedin_client, "_default_author", lambda: "")

    result = linkedin_client.token_diagnostics()

    assert result["ok"] is False
    assert result["status"] == "missing_token"
    assert result["token_present"] is False
    assert "w_organization_social" in result["required_scopes"]


def test_list_administered_organizations_maps_acl_urns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        linkedin_client,
        "token_diagnostics",
        lambda: {"ok": True, "me": {"ok": True, "data": {"id": "abc123"}}},
    )
    monkeypatch.setattr(
        linkedin_client,
        "_request_result",
        lambda method, url, data=None: {
            "ok": True,
            "data": {
                "elements": [
                    {
                        "organization": "urn:li:organization:111",
                        "role": "ADMINISTRATOR",
                        "state": "APPROVED",
                    }
                ]
            },
        },
    )

    result = linkedin_client.list_administered_organizations()

    assert result["ok"] is True
    assert result["member_urn"] == "urn:li:person:abc123"
    assert result["organizations"][0]["organization_id"] == "111"


def test_list_administered_organizations_reports_scope_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        linkedin_client,
        "token_diagnostics",
        lambda: {"ok": True, "me": {"ok": True, "data": {"id": "abc123"}}},
    )
    monkeypatch.setattr(
        linkedin_client,
        "_request_result",
        lambda method, url, data=None: {"ok": False, "http_status": 403, "error": "forbidden"},
    )

    result = linkedin_client.list_administered_organizations()

    assert result["ok"] is False
    assert result["error"] == "organization_acl_unavailable"
    assert "admin role on each LinkedIn Page" in result["requires"]


def test_social_token_ok_accepts_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(editorial_social.config_store, "get", lambda key: "")
    monkeypatch.setattr(editorial_social, "LINKEDIN_ACCESS_TOKEN", "env-token")

    assert editorial_social._token_ok() is True


def test_seed_standard_entities_upserts_four_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class FakeEntities:
        def update_one(self, query, patch, upsert=False):
            calls.append((query, patch, upsert))
            return SimpleNamespace(upserted_id=None, modified_count=1)

    monkeypatch.setattr(editorial_social.mongo_store, "get_db", lambda: SimpleNamespace(entities=FakeEntities()))

    result = editorial_social.seed_standard_entities()

    assert result["ok"] is True
    assert result["entities"] == ["ent_rafael_personal", "ent_innerchispa", "ent_pcdoctor", "ent_innerspark"]
    assert len(calls) == 4
