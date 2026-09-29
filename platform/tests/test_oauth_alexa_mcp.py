import base64
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

for name in tuple(sys.modules):
    if name == "inneros_core_runtime" or name.startswith("inneros_core_runtime."):
        sys.modules.pop(name, None)

from inneros_core_runtime import auth_server, oauth_store, settings
from inneros_core_runtime.oauth_metadata import authorization_server_metadata, protected_resource_metadata


RESOURCE = "https://voz.pcdoctor.ai/mcp"
REDIRECT = "https://pitangui.amazon.com/api/skill/link/MTESTVENDOR"


class Collection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id="fixture")

    def find_one(self, query):
        for doc in self.docs:
            matched = True
            for key, expected in query.items():
                actual = doc.get(key)
                if isinstance(expected, dict) and "$ne" in expected:
                    if actual == expected["$ne"]:
                        matched = False
                        break
                elif actual != expected:
                    matched = False
                    break
            if matched:
                return doc
        return None

    def update_one(self, query, update):
        doc = self.find_one(query)
        if doc and "$set" in update:
            doc.update(update["$set"])
        return SimpleNamespace(modified_count=1 if doc else 0)


class DB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, Collection())



def test_small_router_resource_is_canonical_and_exact():
    resource = "https://mcp.pcdoctor.ai/router/mcp"
    assert resource in settings.OAUTH_ACCEPTED_MCP_RESOURCES
    assert "https://mcp.pcdoctor.ai/router" not in settings.OAUTH_ACCEPTED_MCP_RESOURCES
    assert "https://mcp.pcdoctor.ai/router/mcp/other" not in settings.OAUTH_ACCEPTED_MCP_RESOURCES


def test_router_protected_resource_metadata_is_exact_and_fail_closed():
    resource = "https://mcp.pcdoctor.ai/router/mcp"
    meta = protected_resource_metadata(
        "mcp.pcdoctor.ai",
        resource_override=resource,
    )
    assert meta["resource"] == resource
    with pytest.raises(ValueError, match="oauth_resource_not_accepted"):
        protected_resource_metadata(
            "mcp.pcdoctor.ai",
            resource_override="https://mcp.pcdoctor.ai/router/mcp/other",
        )


def test_router_protected_resource_metadata_route_is_declared():
    source = (PLATFORM_DIR / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
    assert '@mcp.custom_route("/.well-known/oauth-protected-resource/router/mcp"' in source
    assert 'resource_override="https://mcp.pcdoctor.ai/router/mcp"' in source

def test_metadata_matches_official_alexa_authorization_code_flow():
    meta = authorization_server_metadata("auth.pcdoctor.ai")
    assert meta["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert "client_credentials" not in meta["grant_types_supported"]
    assert meta["code_challenge_methods_supported"] == ["S256"]


def test_static_alexa_client_returns_secret_but_stores_only_hash():
    db = DB()
    with patch.object(oauth_store, "ensure_indexes"), patch.object(
        oauth_store, "get_db", return_value=db
    ), patch.object(
        oauth_store, "redirect_uri_allowed", return_value=True
    ), patch.object(
        oauth_store, "OAUTH_ACCEPTED_MCP_RESOURCES", (RESOURCE,)
    ):
        client = oauth_store.create_client(
            {
                "client_name": "Alexa Owner MCP",
                "redirect_uris": [REDIRECT],
                "grant_types": ["authorization_code", "refresh_token"],
                "scope": "ralfia:read",
                "resources": [RESOURCE],
                "token_endpoint_auth_method": "client_secret_basic",
            }
        )

    stored = db[oauth_store.COL_OAUTH_CLIENTS].docs[0]
    assert client["client_secret"]
    assert "client_secret" not in stored
    assert stored["client_secret_hash"]
    assert oauth_store.verify_client_secret(stored, client["client_secret"])
    assert client["grant_types"] == ["authorization_code", "refresh_token"]
    assert client["resources"] == [RESOURCE]


def test_client_credentials_grant_is_rejected():
    db = DB()
    with patch.object(oauth_store, "ensure_indexes"), patch.object(
        oauth_store, "get_db", return_value=db
    ), patch.object(
        oauth_store, "redirect_uri_allowed", return_value=True
    ), patch.object(
        oauth_store, "OAUTH_ACCEPTED_MCP_RESOURCES", (RESOURCE,)
    ):
        with pytest.raises(ValueError, match="Only authorization_code"):
            oauth_store.create_client(
                {
                    "client_name": "Alexa Owner MCP",
                    "redirect_uris": [REDIRECT],
                    "grant_types": ["client_credentials", "authorization_code"],
                    "scope": "ralfia:read",
                    "resources": [RESOURCE],
                    "token_endpoint_auth_method": "client_secret_basic",
                }
            )


def test_registered_redirect_uri_is_exact_not_host_wide():
    registered = [REDIRECT]
    assert oauth_store.redirect_uri_allowed(REDIRECT, registered)
    assert not oauth_store.redirect_uri_allowed(
        "https://pitangui.amazon.com/api/skill/link/OTHER",
        registered,
    )


def test_access_token_validation_can_bind_scope_and_resource():
    db = DB()
    db[oauth_store.COL_OAUTH_TOKENS].docs.append(
        {
            "access_token": "fixture-token",
            "scope": "ralfia:read",
            "resource": RESOURCE,
            "expires_at": oauth_store.now_utc() + timedelta(minutes=10),
            "revoked": False,
        }
    )
    with patch.object(oauth_store, "get_db", return_value=db):
        assert oauth_store.validate_access_token(
            "fixture-token",
            required_scope="ralfia:read",
            required_resource=RESOURCE,
        )
        assert oauth_store.validate_access_token(
            "fixture-token",
            required_scope="ralfia:write",
            required_resource=RESOURCE,
        ) is None
        assert oauth_store.validate_access_token(
            "fixture-token",
            required_scope="ralfia:read",
            required_resource="https://wrong.example/mcp",
        ) is None


def test_authorization_code_is_bound_to_original_resource():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    db = DB()
    db[oauth_store.COL_OAUTH_CODES].docs.append(
        {
            "_id": "code-id",
            "code": "auth-code",
            "client_id": "alexa-client",
            "redirect_uri": REDIRECT,
            "scope": "ralfia:read",
            "username": "owner",
            "code_challenge": oauth_store._pkce_s256(verifier),
            "code_challenge_method": "S256",
            "resource": RESOURCE,
            "expires_at": oauth_store.now_utc() + timedelta(minutes=5),
            "used": False,
        }
    )
    with patch.object(oauth_store, "get_db", return_value=db):
        assert oauth_store.consume_auth_code(
            code="auth-code",
            client_id="alexa-client",
            redirect_uri=REDIRECT,
            code_verifier=verifier,
            resource="https://wrong.example/mcp",
        ) is None
        accepted = oauth_store.consume_auth_code(
            code="auth-code",
            client_id="alexa-client",
            redirect_uri=REDIRECT,
            code_verifier=verifier,
            resource=RESOURCE,
        )
    assert accepted is not None
    assert accepted["resource"] == RESOURCE


def test_basic_client_auth_parser():
    credential = base64.b64encode(b"alexa-client:secret").decode("ascii")
    request = SimpleNamespace(headers={"Authorization": f"Basic {credential}"})
    assert auth_server._basic_client_credentials(request) == (
        "alexa-client",
        "secret",
    )



def test_authorize_form_renders_css_and_hidden_fields():
    html_text = auth_server._authorize_form(
        {
            "response_type": "code",
            "client_id": "alexa-client",
            "redirect_uri": REDIRECT,
            "scope": "ralfia:read",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "resource": RESOURCE,
            "state": "state-1",
        },
        "https://auth.pcdoctor.ai",
    )
    assert "InnerOS Unified SSO" in html_text
    assert "font-family:" in html_text
    assert 'name="client_id" value="alexa-client"' in html_text
    assert 'action="https://auth.pcdoctor.ai/authorize"' in html_text

