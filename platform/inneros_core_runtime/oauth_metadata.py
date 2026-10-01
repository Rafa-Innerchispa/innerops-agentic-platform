"""OAuth & OIDC Metadata for InnerOS Unified Identity Plane."""

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


def resolve_oauth_urls(host_header: str | None = None, request_path: str | None = None) -> tuple[str, str]:
    if is_private_host(host_header):
        issuer = OAUTH_ISSUER_LAN
        resource = OAUTH_MCP_RESOURCE_LAN
    else:
        issuer = OAUTH_ISSUER
        resource = OAUTH_MCP_RESOURCE
    path = (request_path or "").lower()
    if "/router" in path or path.rstrip("/").endswith("/router/mcp"):
        public_base = OAUTH_MCP_RESOURCE.rsplit("/mcp", 1)[0].rstrip("/")
        resource = f"{public_base}/router/mcp"
    elif not resource.endswith("/mcp"):
        resource = f"{resource.rstrip('/')}/mcp"
    return issuer.rstrip("/"), resource


def authorization_server_metadata(host_header: str | None = None) -> dict[str, Any]:
    issuer, _resource = resolve_oauth_urls(host_header)
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "userinfo_endpoint": f"{issuer}/userinfo",
        "introspection_endpoint": f"{issuer}/introspect",
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "registration_endpoint": f"{issuer}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": list(oauth_store.SCOPES),
        "claims_supported": ["sub", "preferred_username", "role", "scopes", "name", "email"],
        "client_id_metadata_document_supported": False,
    }


def _accepted_resource(resource: str) -> None:
    from inneros_core_runtime import settings

    normalized = resource.rstrip("/")
    accepted = {item.rstrip("/") for item in settings.OAUTH_ACCEPTED_MCP_RESOURCES}
    if normalized not in accepted:
        raise ValueError("oauth_resource_not_accepted")


def build_oauth_www_authenticate(
    resource_metadata_url: str,
    *,
    scope: str = "ralfia:read",
) -> str:
    """RFC 6750-style challenge pointing at OAuth protected-resource metadata."""
    safe_url = resource_metadata_url.strip().replace('"', "")
    return f'Bearer resource_metadata="{safe_url}", scope="{scope}"'


def protected_resource_metadata(
    host_header: str | None = None,
    *,
    request_path: str | None = None,
    resource_override: str | None = None,
) -> dict[str, Any]:
    issuer, resource = resolve_oauth_urls(host_header, request_path=request_path)
    if resource_override:
        resource = resource_override.rstrip("/")
        _accepted_resource(resource)
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
