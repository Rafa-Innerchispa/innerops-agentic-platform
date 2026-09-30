"""MCP Federation and Multi-Backend Router with Session Pooling and Internal Auth."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any
import httpx

try:
    from raphiia_openai.settings import MCP_API_KEY
except ImportError:
    try:
        from inneros_core_runtime.settings import MCP_API_KEY
    except ImportError:
        MCP_API_KEY = os.environ.get("MCP_API_KEY", "")


@dataclass
class BackendEndpoint:
    name: str
    url: str
    is_default: bool = False
    prefixes: list[str] = field(default_factory=list)
    timeout_sec: float = 30.0
    active_session_id: str | None = None


class FederationManager:
    def __init__(self, backends_config: dict[str, Any] | None = None) -> None:
        self.backends: dict[str, BackendEndpoint] = {}
        self.default_backend_name: str | None = None
        self._lock = asyncio.Lock()

        if backends_config:
            for key, conf in backends_config.items():
                is_def = conf.get("default", False)
                ep = BackendEndpoint(
                    name=conf.get("name", key),
                    url=conf.get("url", "http://127.0.0.1:8102/mcp"),
                    is_default=is_def,
                    prefixes=conf.get("prefixes", []),
                    timeout_sec=float(conf.get("timeout_sec", 30.0)),
                )
                self.backends[key] = ep
                if is_def or self.default_backend_name is None:
                    self.default_backend_name = key
        else:
            self.backends["monolith"] = BackendEndpoint(
                name="Monolithic MCP Server",
                url="http://127.0.0.1:8102/mcp",
                is_default=True,
                prefixes=["*"],
            )
            self.default_backend_name = "monolith"

    def resolve_backend_for_tool(self, tool_name: str) -> BackendEndpoint:
        """Resolve which backend server handles the given tool name."""
        for name, backend in self.backends.items():
            if not backend.is_default:
                for prefix in backend.prefixes:
                    if tool_name.startswith(prefix):
                        return backend
        if self.default_backend_name and self.default_backend_name in self.backends:
            return self.backends[self.default_backend_name]
        return next(iter(self.backends.values()))

    def get_default_backend(self) -> BackendEndpoint:
        if self.default_backend_name and self.default_backend_name in self.backends:
            return self.backends[self.default_backend_name]
        return next(iter(self.backends.values()))

    async def _ensure_backend_session(self, backend: BackendEndpoint, client: httpx.AsyncClient) -> str | None:
        """Ensure an active FastMCP session ID exists for the backend."""
        if backend.active_session_id:
            return backend.active_session_id

        async with self._lock:
            if backend.active_session_id:
                return backend.active_session_id

            init_payload = {
                "jsonrpc": "2.0",
                "id": "gateway_init_session",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "MCP-Gateway-Router", "version": "2.0.0"}
                }
            }
            init_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if MCP_API_KEY:
                init_headers["X-API-Key"] = MCP_API_KEY

            try:
                resp = await client.post(backend.url, json=init_payload, headers=init_headers)
                sess_id = resp.headers.get("mcp-session-id")
                if sess_id:
                    backend.active_session_id = sess_id
                    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                    notif_headers = dict(init_headers)
                    notif_headers["mcp-session-id"] = sess_id
                    await client.post(backend.url, json=notif, headers=notif_headers)
                return backend.active_session_id
            except Exception:
                return None

    async def forward_jsonrpc_post(self, backend: BackendEndpoint, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Forward a standard JSON-RPC HTTP POST request to upstream backend with session and auth propagation."""
        req_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if MCP_API_KEY:
            req_headers["X-API-Key"] = MCP_API_KEY

        if headers:
            for k, v in headers.items():
                if k.lower() not in ("content-length", "host", "accept"):
                    req_headers[k] = v

        async with httpx.AsyncClient(timeout=backend.timeout_sec) as client:
            if payload.get("method") != "initialize":
                sess_id = await self._ensure_backend_session(backend, client)
                if sess_id and "mcp-session-id" not in req_headers:
                    req_headers["mcp-session-id"] = sess_id

            resp = await client.post(backend.url, json=payload, headers=req_headers)
            
            if resp.status_code == 400 and "Missing session ID" in resp.text:
                backend.active_session_id = None
                sess_id = await self._ensure_backend_session(backend, client)
                if sess_id:
                    req_headers["mcp-session-id"] = sess_id
                resp = await client.post(backend.url, json=payload, headers=req_headers)

            resp.raise_for_status()
            
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                return resp.json()
            elif resp.text.startswith("event:") or resp.text.startswith("data:"):
                lines = resp.text.strip().split("\n")
                for line in lines:
                    if line.startswith("data:"):
                        return json.loads(line[5:].strip())
            return resp.json()
