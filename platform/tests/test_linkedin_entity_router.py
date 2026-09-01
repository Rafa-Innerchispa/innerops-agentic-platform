from types import SimpleNamespace
import urllib.parse

import pytest

from inneros_core_runtime import config_store, editorial_social, linkedin_client


def test_token_diagnostics_reports_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linkedin_client, "_token", lambda *args, **kwargs: "")
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
    for _, patch, _ in calls:
        assert set(patch["$set"]).isdisjoint(patch["$setOnInsert"])


def test_linkedin_oauth_keys_are_in_config_catalog() -> None:
    keys = {row["key"] for row in config_store.CONFIG_CATALOG}

    assert {"LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_REDIRECT_URI"}.issubset(keys)
    assert {
        "LINKEDIN_PERSONAL_ACCESS_TOKEN",
        "LINKEDIN_ORG_ACCESS_TOKEN",
        "LINKEDIN_PERSONAL_CLIENT_ID",
        "LINKEDIN_PERSONAL_CLIENT_SECRET",
        "LINKEDIN_ORG_CLIENT_ID",
        "LINKEDIN_ORG_CLIENT_SECRET",
    }.issubset(keys)


def test_config_store_set_delegates_to_set_values(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_set_values(updates, *, updated_by="PANEL", sync_env=True):
        calls.append((updates, updated_by, sync_env))
        return {"ok": True, "updated": list(updates)}

    monkeypatch.setattr(config_store, "set_values", fake_set_values)

    result = config_store.set("LINKEDIN_ACCESS_TOKEN", "token-value", updated_by="TEST", sync_env=False)

    assert result["ok"] is True
    assert calls == [({"LINKEDIN_ACCESS_TOKEN": "token-value"}, "TEST", False)]


def test_linkedin_oauth_authorization_url_uses_configured_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "LINKEDIN_PERSONAL_CLIENT_ID": "personal-client-id",
        "LINKEDIN_REDIRECT_URI": "https://www.linkedin.com/developers/tools/oauth/redirect",
    }
    monkeypatch.setattr(linkedin_client.config_store, "get", lambda key: values.get(key, ""))

    result = linkedin_client.oauth_authorization_url(["openid", "profile", "email", "w_member_social"], state="state-1", mode="personal")

    parsed = urllib.parse.urlparse(result["url"])
    query = urllib.parse.parse_qs(parsed.query)
    assert result["ok"] is True
    assert parsed.netloc == "www.linkedin.com"
    assert query["client_id"] == ["personal-client-id"]
    assert query["redirect_uri"] == ["https://www.linkedin.com/developers/tools/oauth/redirect"]
    assert query["scope"] == ["openid profile email w_member_social"]
    assert query["state"] == ["state-1"]
    assert result["organization_posting_ready"] is False


def test_linkedin_oauth_authorization_url_can_use_org_app(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "LINKEDIN_ORG_CLIENT_ID": "org-client-id",
        "LINKEDIN_REDIRECT_URI": "https://www.linkedin.com/developers/tools/oauth/redirect",
    }
    monkeypatch.setattr(linkedin_client.config_store, "get", lambda key: values.get(key, ""))

    result = linkedin_client.oauth_authorization_url(state="state-2", mode="organization")

    query = urllib.parse.parse_qs(urllib.parse.urlparse(result["url"]).query)
    assert result["ok"] is True
    assert result["mode"] == "organization"
    assert query["client_id"] == ["org-client-id"]
    assert "w_organization_social" in query["scope"][0]
    assert result["organization_posting_ready"] is True


def test_linkedin_exchange_code_reports_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linkedin_client.config_store, "get", lambda key: "")

    result = linkedin_client.exchange_authorization_code("code-1")

    assert result["ok"] is False
    assert result["error"] == "missing_oauth_config"
    assert "LINKEDIN_CLIENT_ID" in result["missing"]


def test_linkedin_token_selection_prefers_mode_specific_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "LINKEDIN_ACCESS_TOKEN": "generic-token",
        "LINKEDIN_PERSONAL_ACCESS_TOKEN": "personal-token",
        "LINKEDIN_ORG_ACCESS_TOKEN": "org-token",
    }
    monkeypatch.setattr(linkedin_client.config_store, "get", lambda key: values.get(key, ""))

    assert linkedin_client._token("personal") == "personal-token"
    assert linkedin_client._token("organization") == "org-token"
    assert linkedin_client._token(author_urn="urn:li:person:abc") == "personal-token"
    assert linkedin_client._token(author_urn="urn:li:organization:123") == "org-token"


def test_linkedin_exchange_code_stores_mode_specific_token(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "LINKEDIN_ORG_CLIENT_ID": "org-client-id",
        "LINKEDIN_ORG_CLIENT_SECRET": "org-secret",
        "LINKEDIN_REDIRECT_URI": "https://www.linkedin.com/developers/tools/oauth/redirect",
    }
    saved = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"access_token":"new-org-token","expires_in":5184000,"scope":"w_organization_social"}'

    monkeypatch.setattr(linkedin_client.config_store, "get", lambda key: values.get(key, ""))
    monkeypatch.setattr(linkedin_client.config_store, "set_values", lambda updates, **kwargs: saved.append(updates) or {"ok": True})
    monkeypatch.setattr(linkedin_client.config_store, "mask_secret", lambda value: "masked")
    monkeypatch.setattr(linkedin_client, "token_diagnostics", lambda: {"ok": True})
    monkeypatch.setattr(linkedin_client.urllib.request, "urlopen", lambda req, timeout=60: FakeResponse())

    result = linkedin_client.exchange_authorization_code("code-1", mode="organization")

    assert result["ok"] is True
    assert result["mode"] == "organization"
    assert saved == [{"LINKEDIN_ORG_ACCESS_TOKEN": "new-org-token", "LINKEDIN_ACCESS_TOKEN": "new-org-token"}]
