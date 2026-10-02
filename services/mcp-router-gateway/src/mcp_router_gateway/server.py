from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import load_config
from .errors import JSONRPC_PARSE_ERROR, jsonrpc_error
from .router import McpRouter


class RouterHttpHandler(BaseHTTPRequestHandler):
    router: McpRouter

    server_version = "McpRouterGateway/0.2"

    def _normalized_path(self) -> str:
        return self.path.split("?", 1)[0].rstrip("/") or "/"

    def _is_health_path(self) -> bool:
        return self._normalized_path() in {"/", "/health", "/router/health"}

    def _is_mcp_probe_path(self) -> bool:
        return self._normalized_path() in {"/mcp", "/router/mcp"}

    def _is_oauth_metadata_path(self) -> bool:
        return self._normalized_path() in {
            "/.well-known/oauth-protected-resource",
            "/mcp/.well-known/oauth-protected-resource",
            "/router/mcp/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/router/mcp",
        }

    def _has_bearer_auth(self) -> bool:
        auth = (self.headers.get("Authorization") or "").strip()
        return auth.lower().startswith("bearer ") and len(auth) > 7

    def _oauth_metadata_url(self) -> str:
        return (self.router.config.public_url or self.router.config.oauth_resource).rstrip("/") + "/.well-known/oauth-protected-resource"

    def _send_oauth_challenge(self) -> None:
        metadata_url = self._oauth_metadata_url()
        self._send_json(
            {
                "ok": False,
                "error": "authentication_required",
                "resource_metadata": metadata_url,
            },
            status=401,
        )

    def do_GET(self) -> None:
        if self._is_oauth_metadata_path():
            self._send_json(self._oauth_metadata())
            return
        if self._is_health_path():
            self._send_json(
                {
                    "ok": True,
                    "service": "mcp-router-gateway",
                    "profile": self.router.profile_name,
                    "public_url": self.router.config.public_url,
                    "backends": sorted(self.router.config.backends),
                    **self.router.health_snapshot(),
                }
            )
            return
        if self._is_mcp_probe_path():
            if not self._has_bearer_auth():
                self._send_oauth_challenge()
                return
            self.send_error(405, explain="Authenticated MCP entry requires POST or SSE GET")
            return
        self.send_error(404)

    def do_HEAD(self) -> None:
        if self._is_oauth_metadata_path():
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self._is_health_path():
            self.send_response(200)
            self.send_header("X-InnerOS-MCP-Endpoint", self.router.config.public_url or "/mcp")
            self.send_header("X-InnerOS-MCP-Transport", "streamable-http")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self._is_mcp_probe_path():
            if not self._has_bearer_auth():
                metadata_url = self._oauth_metadata_url()
                self.send_response(401)
                self.send_header(
                    "WWW-Authenticate",
                    f'Bearer resource_metadata="{metadata_url}", scope="ralfia:read ralfia:write ralfia:agents"',
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_error(405)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_oauth_challenge()
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload: dict[str, Any] | list[Any] = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(jsonrpc_error(None, JSONRPC_PARSE_ERROR, "Parse error"))
            return
        session_id = self.headers.get("Mcp-Session-Id", "")
        reply = (
            self.router.handle_with_session(
                payload,
                session_id=session_id,
                authorization=self.headers.get("Authorization", ""),
            )
            if isinstance(payload, dict)
            else None
        )
        if reply is None:
            self._send_json(self.router.handle(payload))
            return
        accept = self.headers.get("Accept", "")
        if "text/event-stream" in accept:
            self._send_sse(reply.payload, session_id=reply.session_id)
            return
        self._send_json(reply.payload, session_id=reply.session_id)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _authorized(self) -> bool:
        token = self.router.config.bearer_token
        auth = self.headers.get("Authorization", "")
        if self.router.config.auth_mode == "oauth_passthrough":
            return self._has_bearer_auth()
        if not token:
            return True
        return auth == f"Bearer {token}"

    def _oauth_metadata(self) -> dict[str, Any]:
        return {
            "resource": self.router.config.oauth_resource,
            "authorization_servers": [self.router.config.oauth_authorization_server],
            "scopes_supported": [
                "openid",
                "profile",
                "email",
                "ralfia:read",
                "ralfia:write",
                "ralfia:agents",
                "ralfia:admin",
                "ralfia:memory:read",
                "ralfia:memory:write",
                "ralfia:memory:finalize",
                "ralfia:private_memory",
            ],
            "bearer_methods_supported": ["header"],
            "resource_documentation": "https://developers.openai.com/apps-sdk/build/auth",
            "mcp_public_url": self.router.config.public_url or self.router.config.oauth_resource,
            "router_profile": self.router.profile_name,
        }

    def _send_json(self, payload: Any, status: int = 200, *, session_id: str = "") -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if status == 401 and self.router.config.auth_mode == "oauth_passthrough":
            metadata_url = self._oauth_metadata_url()
            self.send_header(
                "WWW-Authenticate",
                f'Bearer resource_metadata="{metadata_url}", scope="ralfia:read ralfia:write ralfia:agents"',
            )
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, payload: Any, status: int = 200, *, session_id: str = "") -> None:
        body = ("event: message\n" + "data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run() -> None:
    config = load_config()
    router = McpRouter(config)
    RouterHttpHandler.router = router
    server = ThreadingHTTPServer((config.host, config.port), RouterHttpHandler)
    print(
        json.dumps(
            {
                "ok": True,
                "service": "mcp-router-gateway",
                "listen": f"http://{config.host}:{config.port}",
                "public_url": config.public_url,
                "backends": sorted(config.backends),
                "profile": config.active_profile,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP Router Gateway")
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
