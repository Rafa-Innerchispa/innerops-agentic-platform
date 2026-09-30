"""MCP federation with session pooling and idempotency-gated failover."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import os
from typing import Any

import httpx

try:
    from raphiia_openai.settings import MCP_API_KEY
except ImportError:
    try:
        from inneros_core_runtime.settings import MCP_API_KEY
    except ImportError:
        MCP_API_KEY = os.environ.get("MCP_API_KEY", "")


SAFE_PROTOCOL_METHODS = {
    "initialize",
    "ping",
    "tools/list",
    "resources/list",
    "resources/templates/list",
    "prompts/list",
}
SAFE_TOOL_NAMES = {
    "mcp_version",
    "a2a_status",
    "dev_swarm_scheduler_status",
    "get_coordination_status",
    "search_capabilities",
    "describe_capability",
}
SAFE_TOOL_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "describe_",
    "diagnose_",
    "query_",
    "poll_",
)


def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


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
        self.failover_enabled = _env_enabled("INNEROS_MCP_FAILOVER_ENABLED", False)

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
        """Resolve which primary backend handles a tool name."""
        for backend in self.backends.values():
            if not backend.is_default:
                for prefix in backend.prefixes:
                    if tool_name.startswith(prefix):
                        return backend
        return self.get_default_backend()

    def get_default_backend(self) -> BackendEndpoint:
        if self.default_backend_name and self.default_backend_name in self.backends:
            return self.backends[self.default_backend_name]
        return next(iter(self.backends.values()))

    def _candidate_backends(self, primary: BackendEndpoint) -> list[BackendEndpoint]:
        candidates = [primary]
        if self.failover_enabled:
            candidates.extend(
                backend
                for backend in self.backends.values()
                if backend is not primary
            )
        return candidates

    @staticmethod
    def _request_is_idempotent(
        payload: dict[str, Any],
        headers: dict[str, str] | None,
    ) -> bool:
        method = str(payload.get("method") or "")
        if method in SAFE_PROTOCOL_METHODS:
            return True
        if method != "tools/call":
            return False

        params = payload.get("params") or {}
        tool_name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}

        # Broker calls inherit the target capability's risk and idempotency.
        if tool_name == "invoke_capability":
            tool_name = str(arguments.get("capability_id") or "")
            arguments = arguments.get("arguments") or {}

        normalized_headers = {str(key).lower(): value for key, value in (headers or {}).items()}
        explicit_key = (
            normalized_headers.get("idempotency-key")
            or arguments.get("idempotency_key")
            or arguments.get("idempotencyKey")
        )
        if explicit_key:
            return True
        if tool_name in SAFE_TOOL_NAMES:
            return True
        return tool_name.startswith(SAFE_TOOL_PREFIXES)

    async def _ensure_backend_session(
        self,
        backend: BackendEndpoint,
        client: httpx.AsyncClient,
    ) -> str | None:
        """Ensure a FastMCP session exists for one backend."""
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
                    "clientInfo": {
                        "name": "MCP-Gateway-Router",
                        "version": "2.0.0",
                    },
                },
            }
            init_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if MCP_API_KEY:
                init_headers["X-API-Key"] = MCP_API_KEY

            response = await client.post(
                backend.url,
                json=init_payload,
                headers=init_headers,
            )
            response.raise_for_status()
            session_id = response.headers.get("mcp-session-id")
            if session_id:
                backend.active_session_id = session_id
                notification_headers = dict(init_headers)
                notification_headers["mcp-session-id"] = session_id
                await client.post(
                    backend.url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers=notification_headers,
                )
            return backend.active_session_id

    async def _forward_once(
        self,
        backend: BackendEndpoint,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
    ) -> dict[str, Any]:
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if MCP_API_KEY:
            request_headers["X-API-Key"] = MCP_API_KEY
        if headers:
            for key, value in headers.items():
                if key.lower() not in ("content-length", "host", "accept"):
                    request_headers[key] = value

        async with httpx.AsyncClient(timeout=backend.timeout_sec) as client:
            if payload.get("method") != "initialize":
                session_id = await self._ensure_backend_session(backend, client)
                if session_id and "mcp-session-id" not in request_headers:
                    request_headers["mcp-session-id"] = session_id

            response = await client.post(
                backend.url,
                json=payload,
                headers=request_headers,
            )
            if response.status_code == 400 and "Missing session ID" in response.text:
                backend.active_session_id = None
                session_id = await self._ensure_backend_session(backend, client)
                if session_id:
                    request_headers["mcp-session-id"] = session_id
                response = await client.post(
                    backend.url,
                    json=payload,
                    headers=request_headers,
                )

            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.json()
            if response.text.startswith("event:") or response.text.startswith("data:"):
                for line in response.text.strip().split("\n"):
                    if line.startswith("data:"):
                        return json.loads(line[5:].strip())
            return response.json()

    async def forward_jsonrpc_post(
        self,
        backend: BackendEndpoint,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Forward to primary and safely fail over only when replay is idempotent."""
        replay_safe = self._request_is_idempotent(payload, headers)
        candidates = self._candidate_backends(backend)
        if not replay_safe:
            candidates = candidates[:1]

        failures: list[str] = []
        for candidate in candidates:
            try:
                return await self._forward_once(candidate, payload, headers)
            except httpx.HTTPStatusError as exc:
                # Authentication, authorization, validation and other client
                # failures must never be hidden by trying another backend.
                if exc.response.status_code < 500:
                    raise
                candidate.active_session_id = None
                failures.append(f"{candidate.name}:http_{exc.response.status_code}")
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                candidate.active_session_id = None
                failures.append(f"{candidate.name}:{type(exc).__name__}")

        if failures:
            raise RuntimeError(
                "MCPBackendUnavailable: failover exhausted ("
                + ", ".join(failures)
                + ")"
            )
        raise RuntimeError("MCPBackendUnavailable: no backend candidates")
