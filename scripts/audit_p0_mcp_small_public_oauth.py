#!/usr/bin/env python3
"""Read-only public contract audit for the canonical InnerOS MCP Small."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

MCP = "https://mcp.pcdoctor.ai/router/mcp"
HEALTH = "https://mcp.pcdoctor.ai/router/health"
RESOURCE_METADATA = "https://mcp.pcdoctor.ai/router/mcp/.well-known/oauth-protected-resource"
ISSUER = "https://auth.pcdoctor.ai"
AUTH_METADATA = f"{ISSUER}/.well-known/oauth-authorization-server"


def _header_value(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""


def request_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> tuple[int, dict[str, str], Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "inneros-p0-public-audit/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.status, dict(response.headers), json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, dict(exc.headers), parsed


def main() -> int:
    checks: dict[str, Any] = {}
    failures: list[str] = []

    status, _, health = request_json(HEALTH)
    checks["health"] = {"status": status, "body": health}
    if status != 200 or health.get("service") != "mcp-router-gateway" or health.get("profile") != "chatgpt_compact":
        failures.append("gateway health/profile contract failed")

    status, _, protected = request_json(RESOURCE_METADATA)
    checks["protected_resource"] = {"status": status, "body": protected}
    if status != 200 or protected.get("resource") != MCP or protected.get("authorization_servers") != [ISSUER]:
        failures.append("protected-resource metadata mismatch")

    status, _, auth = request_json(AUTH_METADATA)
    checks["authorization_server"] = {"status": status, "body": auth}
    if status != 200 or auth.get("issuer") != ISSUER or "S256" not in auth.get("code_challenge_methods_supported", []):
        failures.append("authorization-server metadata/PKCE contract failed")

    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "inneros-p0-public-audit", "version": "1.0"},
        },
    }
    status, headers, body = request_json(MCP, method="POST", body=initialize)
    challenge = _header_value(headers, "WWW-Authenticate")
    checks["unauthenticated_initialize"] = {"status": status, "www_authenticate": challenge, "body": body}
    if status != 401:
        failures.append("MCP unauthenticated initialize did not fail closed")
    if not challenge:
        failures.append("MCP OAuth challenge is missing WWW-Authenticate")
    elif RESOURCE_METADATA not in challenge:
        failures.append("MCP OAuth challenge advertised the wrong resource metadata URL")

    result = {
        "ok": not failures,
        "mode": "read_only_public_mcp_small_oauth_audit",
        "mcp_url": MCP,
        "oauth_resource": MCP,
        "issuer": ISSUER,
        "failures": failures,
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
