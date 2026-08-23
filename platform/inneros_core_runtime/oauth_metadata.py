"""Metadatos OAuth compartidos — URLs públicas (ChatGPT) vs LAN (IP interna)."""

from __future__ import annotations

import ipaddress
from typing import Any

from raphiia_openai import oauth_store
from raphiia_openai.settings import (
    MCP_LAN_URL,
    MCP_PUBLIC_URL,
    OAUTH_ISSUER,
    OAUTH_ISSUER_LAN,
    OAUTH_MCP_RESOURCE,
    OAUTH_MCP_RESOURCE_LAN,
    RALFIA_INTEL_HOST,
)


def _hostname(host_header: str | None) -> str:
    raw = (host_header or "").split(",")[0].strip().lower()
    if not raw:
        return ""
    return raw.split(":")[0].strip("[]")


def is_private_host(host_header: str | None) -> bool:
    name = _hostname(host_header)
    if not name:
        return False
    if name in {"localhost", "127.0.0.1"}:
        return True
    try:
        return ipaddress.ip_address(name).is_private
    except ValueError:
        return False


def resolve_oauth_urls(host_header: str | None = None) -> tuple[str, str]:
    """Devuelve (issuer, mcp_resource) según cliente LAN o público."""
    if is_private_host(host_header):
        issuer = OAUTH_ISSUER_LAN
        resource = OAUTH_MCP_RESOURCE_LAN
    else:
        issuer = OAUTH_ISSUER
        resource = OAUTH_MCP_RESOURCE
    if not resource.endswith("/mcp"):
        resource = f"{resource.rstrip('/')}/mcp"
    return issuer.rstrip("/"), resource


def authorization_server_metadata(host_header: str | None = None) -> dict[str, Any]:
    issuer, _resource = resolve_oauth_urls(host_header)
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": list(oauth_store.SCOPES),
        "client_id_metadata_document_supported": False,
    }


def protected_resource_metadata(host_header: str | None = None) -> dict[str, Any]:
    issuer, resource = resolve_oauth_urls(host_header)
    return {
        "resource": resource,
        "authorization_servers": [issuer],
        "scopes_supported": list(oauth_store.SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_documentation": "https://developers.openai.com/apps-sdk/build/auth",
        "mcp_public_url": MCP_PUBLIC_URL.rstrip("/"),
        "mcp_lan_url": MCP_LAN_URL.rstrip("/"),
        "intel_host": RALFIA_INTEL_HOST,
    }
