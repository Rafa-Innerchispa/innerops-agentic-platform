"""Codex / MCP Small — GET /router/mcp must 401 with OAuth metadata, not health JSON."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

from starlette.responses import JSONResponse

from inneros_core_runtime.mcp_server import (
    McpSmallOAuthDiscoveryMiddleware,
    _compact_mcp_oauth_challenge,
    _router_health_payload,
)


async def _noop_app(scope, receive, send):
    response = JSONResponse({"ok": True, "passed_through": True})
    await response(scope, receive, send)


def test_unauthenticated_get_mcp_returns_401_with_resource_metadata():
    mw = McpSmallOAuthDiscoveryMiddleware(_noop_app)
    captured: dict = {}

    async def send(message):
        captured.update(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/router/mcp",
        "headers": [(b"accept", b"application/json")],
    }

    async def run():
        with patch.dict(os.environ, {"MCP_TOOL_PROFILE": "chatgpt_compact"}, clear=False):
            with patch(
                "inneros_core_runtime.auth_middleware.resolve_bearer_auth_context",
                return_value={"ok": False, "auth_mode": "none"},
            ):
                await mw(scope, lambda: None, send)

    asyncio.run(run())

    assert captured.get("status") == 401
    headers = {k.decode(): v.decode() for k, v in captured.get("headers") or []}
    assert "oauth-protected-resource" in headers.get("www-authenticate", "")


def test_health_payload_is_separate_from_mcp_entry():
    payload = _router_health_payload()
    assert payload["service"] == "mcp-router-gateway"
    assert "mcp_endpoint" in payload
    assert "resource" not in payload


def test_challenge_includes_compact_scopes():
    resp = _compact_mcp_oauth_challenge()
    assert resp.status_code == 401
    assert "ralfia:agents" in resp.headers["www-authenticate"]
