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

from inneros_core_runtime import auth_server, oauth_store
from inneros_core_runtime.oauth_metadata import authorization_server_metadata


RESOURCE = "https://owner-mcp.pcdoctor.ai/mcp"


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


def test_metadata_advertises_alexa_two_tier_oauth():
    meta = authorization_server_metadata("auth.pcdoctor.ai")
    assert "client_credentials" in meta["grant_types_supported"]
    assert "authorization_code" in meta["grant_types_supported"]
    assert "refresh_token" in meta["grant_types_supported"]
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert "mcp:service" in meta["scopes_supported"]
    assert "mcp:tools" in meta["scopes_supported"]
    assert "mcp:resources" in meta["scopes_supported"]


def test_alexa_client_registration_returns_secret_but_stores_only_hash():
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
                "redirect_uris": ["https://alexa.amazon.com/api/skill/link/fixture"],
                "grant_types": ["client_credentials", "authorization_code"],
                "scope": "mcp:service mcp:tools mcp:resources",
                "resources": [RESOURCE],
                "token_endpoint_auth_method": "client_secret_basic",
            }
        )

    stored = db[oauth_store.COL_OAUTH_CLIENTS].docs[0]
    assert "client_secret" in client
    assert client["client_secret"]
    assert "client_secret" not in stored
    assert stored["client_secret_hash"]
    assert oauth_store.verify_client_secret(stored, client["client_secret"])
    assert set(client["grant_types"]) == {
        "client_credentials",
        "authorization_code",
        "refresh_token",
    }


def test_client_credentials_token_is_service_only_resource_bound_and_short_lived():
    secret = "service-secret"
    client = {
        "client_id": "alexa-client",
        "client_secret_hash": oauth_store._client_secret_hash(secret),
        "grant_types": ["client_credentials", "authorization_code", "refresh_token"],
        "scope": "mcp:service mcp:tools mcp:resources",
        "resources": [RESOURCE],
        "token_endpoint_auth_method": "client_secret_basic",
    }
    db = DB()
    with patch.object(oauth_store, "ensure_indexes"), patch.object(
        oauth_store, "get_client", return_value=client
    ), patch.object(
        oauth_store, "get_db", return_value=db
    ), patch.object(
        oauth_store, "OAUTH_ACCEPTED_MCP_RESOURCES", (RESOURCE,)
    ):
        token = oauth_store.issue_client_credentials_token(
            client_id="alexa-client",
            client_secret=secret,
            scope="mcp:service",
            resource=RESOURCE,
        )

    assert token["token_type"] == "Bearer"
    assert token["scope"] == "mcp:service"
    assert token["expires_in"] <= 3600
    assert "refresh_token" not in token
    stored = db[oauth_store.COL_OAUTH_TOKENS].docs[0]
    assert stored["grant_type"] == "client_credentials"
    assert stored["username"] is None
    assert stored["resource"] == RESOURCE


def test_client_credentials_rejects_user_scope_and_wrong_resource():
    secret = "service-secret"
    client = {
        "client_id": "alexa-client",
        "client_secret_hash": oauth_store._client_secret_hash(secret),
        "grant_types": ["client_credentials"],
        "scope": "mcp:service",
        "resources": [RESOURCE],
    }
    db = DB()
    with patch.object(oauth_store, "ensure_indexes"), patch.object(
        oauth_store, "get_client", return_value=client
    ), patch.object(
        oauth_store, "get_db", return_value=db
    ), patch.object(
        oauth_store, "OAUTH_ACCEPTED_MCP_RESOURCES", (RESOURCE,)
    ):
        with pytest.raises(ValueError, match="invalid_scope"):
            oauth_store.issue_client_credentials_token(
                client_id="alexa-client",
                client_secret=secret,
                scope="mcp:tools",
                resource=RESOURCE,
            )
        with pytest.raises(ValueError, match="access_denied"):
            oauth_store.issue_client_credentials_token(
                client_id="alexa-client",
                client_secret=secret,
                scope="mcp:service",
                resource="https://other.example/mcp",
            )


def test_access_token_validation_can_bind_scope_and_resource():
    db = DB()
    db[oauth_store.COL_OAUTH_TOKENS].docs.append(
        {
            "access_token": "fixture-token",
            "scope": "mcp:service",
            "resource": RESOURCE,
            "expires_at": oauth_store.now_utc() + timedelta(minutes=10),
            "revoked": False,
        }
    )
    with patch.object(oauth_store, "get_db", return_value=db):
        assert oauth_store.validate_access_token(
            "fixture-token",
            required_scope="mcp:service",
            required_resource=RESOURCE,
        )
        assert oauth_store.validate_access_token(
            "fixture-token",
            required_scope="mcp:tools",
            required_resource=RESOURCE,
        ) is None
        assert oauth_store.validate_access_token(
            "fixture-token",
            required_scope="mcp:service",
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
            "redirect_uri": "https://alexa.amazon.com/api/skill/link/fixture",
            "scope": "mcp:tools mcp:resources",
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
            redirect_uri="https://alexa.amazon.com/api/skill/link/fixture",
            code_verifier=verifier,
            resource="https://wrong.example/mcp",
        ) is None
        accepted = oauth_store.consume_auth_code(
            code="auth-code",
            client_id="alexa-client",
            redirect_uri="https://alexa.amazon.com/api/skill/link/fixture",
            code_verifier=verifier,
            resource=RESOURCE,
        )
    assert accepted is not None
    assert accepted["resource"] == RESOURCE


def test_basic_client_auth_parser_and_mcp_user_scopes_are_least_privilege():
    credential = base64.b64encode(b"alexa-client:secret").decode("ascii")
    request = SimpleNamespace(headers={"Authorization": f"Basic {credential}"})
    assert auth_server._basic_client_credentials(request) == (
        "alexa-client",
        "secret",
    )

    granted = set(
        auth_server._scope_for_user(
            {"role": "admin", "oauth_enabled": True},
            "mcp:tools mcp:resources",
        ).split()
    )
    assert granted == {"mcp:tools", "mcp:resources"}
    assert "ralfia:write" not in granted
