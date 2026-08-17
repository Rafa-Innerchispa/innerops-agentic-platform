"""Mongo-backed OAuth storage and token validation for RalfIA MCP."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from pymongo import MongoClient

from raphiia_openai.settings import (
    COL_OAUTH_CLIENTS,
    COL_OAUTH_CODES,
    COL_OAUTH_REFRESH_TOKENS,
    COL_OAUTH_TOKENS,
    MONGO_DB,
    MONGO_URI,
    OAUTH_ALLOWED_REDIRECT_HOSTS,
    OAUTH_CODE_TTL_SECONDS,
    OAUTH_REFRESH_TTL_SECONDS,
    OAUTH_TOKEN_TTL_SECONDS,
)

SCOPES = (
    "ralfia:read",
    "ralfia:write",
    "ralfia:agents",
    "ralfia:admin",
    "ralfia:memory:read",
    "ralfia:memory:write",
    "ralfia:memory:finalize",
    "ralfia:private_memory",
)
MEMORY_SCOPES = (
    "ralfia:memory:read",
    "ralfia:memory:write",
    "ralfia:memory:finalize",
    "ralfia:private_memory",
)
CHATGPT_SCOPES = MEMORY_SCOPES + ("ralfia:agents",)
DEFAULT_SCOPES = ("ralfia:read", "ralfia:write")

_client: MongoClient | None = None


def get_db():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI)
    return _client[MONGO_DB]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def ensure_indexes() -> None:
    db = get_db()
    db[COL_OAUTH_CLIENTS].create_index("client_id", unique=True)
    db[COL_OAUTH_CODES].create_index("code", unique=True)
    db[COL_OAUTH_CODES].create_index("expires_at", expireAfterSeconds=0)
    db[COL_OAUTH_TOKENS].create_index("access_token", unique=True)
    db[COL_OAUTH_TOKENS].create_index("expires_at", expireAfterSeconds=0)
    db[COL_OAUTH_REFRESH_TOKENS].create_index("refresh_token", unique=True)
    db[COL_OAUTH_REFRESH_TOKENS].create_index("expires_at", expireAfterSeconds=0)


def parse_scopes(scope: str | None) -> list[str]:
    requested = [s for s in (scope or "").split() if s]
    if not requested:
        return list(DEFAULT_SCOPES)
    allowed = [s for s in requested if s in SCOPES]
    return allowed or list(DEFAULT_SCOPES)


def redirect_uri_allowed(uri: str, registered_uris: list[str] | None = None) -> bool:
    if registered_uris and uri in registered_uris:
        return True
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if host in OAUTH_ALLOWED_REDIRECT_HOSTS:
        return True
    if host.endswith(".chatgpt.com") and "chatgpt.com" in OAUTH_ALLOWED_REDIRECT_HOSTS:
        return True
    return False


def create_client(metadata: dict[str, Any]) -> dict[str, Any]:
    ensure_indexes()
    redirect_uris = [u for u in metadata.get("redirect_uris", []) if isinstance(u, str)]
    redirect_uris = [u for u in redirect_uris if redirect_uri_allowed(u)]
    if not redirect_uris:
        raise ValueError("No allowed redirect_uris supplied")

    scopes = parse_scopes(metadata.get("scope"))
    if str(metadata.get("client_name") or "").strip().lower() == "chatgpt":
        scopes = sorted(set(scopes).union(CHATGPT_SCOPES))
    client = {
        "client_id": "ralfia_" + secrets.token_urlsafe(18),
        "client_secret": None,
        "client_name": metadata.get("client_name") or "RalfIA MCP Client",
        "redirect_uris": redirect_uris,
        "scope": " ".join(scopes),
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": metadata.get("token_endpoint_auth_method") or "none",
        "created_at": now_iso(),
        "metadata": metadata,
    }
    get_db()[COL_OAUTH_CLIENTS].insert_one(client)
    return dict(client)


def get_client(client_id: str) -> dict[str, Any] | None:
    return get_db()[COL_OAUTH_CLIENTS].find_one({"client_id": client_id})


def save_auth_code(
    *,
    client_id: str,
    redirect_uri: str,
    scope: str,
    username: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str | None,
) -> str:
    ensure_indexes()
    code = secrets.token_urlsafe(32)
    get_db()[COL_OAUTH_CODES].insert_one(
        {
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "username": username,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "resource": resource,
            "created_at": now_utc(),
            "expires_at": now_utc() + timedelta(seconds=OAUTH_CODE_TTL_SECONDS),
            "used": False,
        }
    )
    return code


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def consume_auth_code(
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any] | None:
    db = get_db()
    doc = db[COL_OAUTH_CODES].find_one({"code": code, "used": False})
    if not doc:
        return None
    if doc.get("client_id") != client_id or doc.get("redirect_uri") != redirect_uri:
        return None
    if doc.get("expires_at") and doc["expires_at"].replace(tzinfo=timezone.utc) < now_utc():
        return None
    if doc.get("code_challenge_method") != "S256":
        return None
    if _pkce_s256(code_verifier) != doc.get("code_challenge"):
        return None
    db[COL_OAUTH_CODES].update_one({"_id": doc["_id"]}, {"$set": {"used": True, "used_at": now_utc()}})
    return doc


def issue_access_token(code_doc: dict[str, Any]) -> dict[str, Any]:
    ensure_indexes()
    token = secrets.token_urlsafe(36)
    refresh_token = secrets.token_urlsafe(44)
    expires_at = now_utc() + timedelta(seconds=OAUTH_TOKEN_TTL_SECONDS)
    refresh_expires_at = now_utc() + timedelta(seconds=OAUTH_REFRESH_TTL_SECONDS)
    doc = {
        "access_token": token,
        "token_type": "Bearer",
        "client_id": code_doc["client_id"],
        "username": code_doc["username"],
        "scope": code_doc.get("scope") or " ".join(DEFAULT_SCOPES),
        "resource": code_doc.get("resource"),
        "created_at": now_utc(),
        "expires_at": expires_at,
        "revoked": False,
    }
    get_db()[COL_OAUTH_TOKENS].insert_one(doc)
    get_db()[COL_OAUTH_REFRESH_TOKENS].insert_one(
        {
            "refresh_token": refresh_token,
            "client_id": code_doc["client_id"],
            "username": code_doc["username"],
            "scope": doc["scope"],
            "resource": code_doc.get("resource"),
            "created_at": now_utc(),
            "expires_at": refresh_expires_at,
            "revoked": False,
        }
    )
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": OAUTH_TOKEN_TTL_SECONDS,
        "scope": doc["scope"],
        "refresh_token": refresh_token,
        "refresh_token_expires_in": OAUTH_REFRESH_TTL_SECONDS,
    }


def exchange_refresh_token(*, refresh_token: str, client_id: str) -> dict[str, Any] | None:
    ensure_indexes()
    db = get_db()
    doc = db[COL_OAUTH_REFRESH_TOKENS].find_one({"refresh_token": refresh_token, "revoked": {"$ne": True}})
    if not doc:
        return None
    if doc.get("client_id") != client_id:
        return None
    expires_at = doc.get("expires_at")
    if expires_at and expires_at.replace(tzinfo=timezone.utc) < now_utc():
        return None
    access_token = secrets.token_urlsafe(36)
    access_expires_at = now_utc() + timedelta(seconds=OAUTH_TOKEN_TTL_SECONDS)
    access_doc = {
        "access_token": access_token,
        "token_type": "Bearer",
        "client_id": client_id,
        "username": doc["username"],
        "scope": doc.get("scope") or " ".join(DEFAULT_SCOPES),
        "resource": doc.get("resource"),
        "created_at": now_utc(),
        "expires_at": access_expires_at,
        "revoked": False,
    }
    db[COL_OAUTH_TOKENS].insert_one(access_doc)
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": OAUTH_TOKEN_TTL_SECONDS,
        "scope": access_doc["scope"],
        "refresh_token": refresh_token,
        "refresh_token_expires_in": max(0, int((expires_at.replace(tzinfo=timezone.utc) - now_utc()).total_seconds())) if expires_at else OAUTH_REFRESH_TTL_SECONDS,
    }


def validate_access_token(access_token: str, required_scope: str | None = None) -> dict[str, Any] | None:
    if not access_token:
        return None
    doc = get_db()[COL_OAUTH_TOKENS].find_one({"access_token": access_token, "revoked": {"$ne": True}})
    if not doc:
        return None
    expires_at = doc.get("expires_at")
    if expires_at and expires_at.replace(tzinfo=timezone.utc) < now_utc():
        return None
    scopes = set((doc.get("scope") or "").split())
    if required_scope and required_scope not in scopes and "ralfia:admin" not in scopes:
        return None
    return doc
