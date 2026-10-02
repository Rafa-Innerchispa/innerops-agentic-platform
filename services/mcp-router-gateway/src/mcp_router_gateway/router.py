from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any

from .backend import BackendResponse, JsonRpcBackendClient
from .config import RouterConfig
from .errors import BackendError, JSONRPC_INVALID_REQUEST, RouterError, ToolNotAllowedError, jsonrpc_error, router_error_response
from .backend_health import BackendHealthCache
from .filtering import (
    filter_tools,
    extract_tools_from_response,
    replace_tools_in_response,
    validate_sandbox_policy,
    validate_tool_allowed,
)


@dataclass(slots=True)
class RouterSession:
    id: str
    initialize_request: dict[str, Any]
    authorization: str = ""
    backend_sessions: dict[str, str] = field(default_factory=dict)
    tool_backend_cache: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouterReply:
    payload: dict[str, Any] | list[Any]
    session_id: str = ""


class McpRouter:
    def __init__(self, config: RouterConfig, backend: JsonRpcBackendClient | None = None) -> None:
        self.config = config
        self._single_backend = backend
        self._backend_clients: dict[str, JsonRpcBackendClient] = {}
        self._sessions: dict[str, RouterSession] = {}
        self._allowed_tool_cache: frozenset[str] | None = None
        self._tool_backend_cache: dict[str, str] = {}
        self._backend_health = BackendHealthCache()

    @property
    def profile_name(self) -> str:
        return self.config.active_profile

    def handle(self, payload: dict[str, Any] | list[Any]) -> dict[str, Any] | list[Any]:
        if isinstance(payload, list):
            return [self._handle_one(item) for item in payload]
        return self._handle_one(payload)

    def handle_with_session(self, payload: dict[str, Any] | list[Any], *, session_id: str = "", authorization: str = "") -> RouterReply:
        if isinstance(payload, list):
            responses = [self._handle_one(item, session_id=session_id) for item in payload]
            return RouterReply(responses, session_id=session_id)
        if payload.get("method") == "initialize":
            return self._initialize(payload, authorization=authorization)
        if not session_id or session_id not in self._sessions:
            return RouterReply(jsonrpc_error(payload.get("id"), JSONRPC_INVALID_REQUEST, "Missing or unknown Mcp-Session-Id"))
        return RouterReply(self._handle_one(payload, session_id=session_id), session_id=session_id)

    def _handle_one(self, request: Any, *, session_id: str = "") -> dict[str, Any]:
        if not isinstance(request, dict):
            return jsonrpc_error(None, JSONRPC_INVALID_REQUEST, "Invalid Request")
        request_id = request.get("id")
        try:
            method = request.get("method")
            if method == "tools/list":
                return self._tools_list(request, session_id=session_id)
            if method == "tools/call":
                return self._tools_call(request, session_id=session_id)
            return self._forward(request, backend_name=self._default_backend_name(), session_id=session_id)
        except RouterError as exc:
            return router_error_response(request_id, exc)

    def _normalize_backend_response(self, response: Any) -> BackendResponse:
        if isinstance(response, BackendResponse):
            return response
        if isinstance(response, (dict, list)):
            return BackendResponse(payload=response)
        raise BackendError("backend returned invalid response")

    def _backend_client(self, backend_name: str) -> Any:
        if self._single_backend is not None:
            return self._single_backend
        target = self.config.backends.get(backend_name)
        if not target or not target.enabled:
            raise BackendError(f"backend is not configured: {backend_name}", data={"backend": backend_name})
        if backend_name not in self._backend_clients:
            self._backend_clients[backend_name] = JsonRpcBackendClient(target.url)
        return self._backend_clients[backend_name]

    def _profile_backend_names(self) -> tuple[str, ...]:
        names = self.config.profile.backends or (self._default_backend_name(),)
        configured = tuple(name for name in names if name in self.config.backends or self._single_backend is not None)
        if self._single_backend is not None or not configured:
            return configured
        healthy = [name for name in configured if self._backend_health.is_healthy(name, self.config)]
        unhealthy = [name for name in configured if name not in healthy]
        return tuple(healthy + unhealthy) if healthy else configured

    def _primary_backend_name(self) -> str:
        ordered = self._profile_backend_names()
        if ordered:
            return ordered[0]
        return self._default_backend_name()

    def health_snapshot(self) -> dict[str, Any]:
        backends = self._backend_health.snapshot(self.config)
        amd_ok = backends.get("inneros_compact_amd", False)
        intel_ok = backends.get("inneros_compact", False)
        if amd_ok:
            mode = "normal_amd_primary"
        elif intel_ok:
            mode = "degraded_intel_only"
        else:
            mode = "degraded_no_compact_backend"
        return {
            "backends_healthy": backends,
            "primary_backend": self._primary_backend_name(),
            "mode": mode,
        }

    def _default_backend_name(self) -> str:
        return self.config.profile.default_backend or self.config.default_backend

    def _session(self, session_id: str) -> RouterSession | None:
        return self._sessions.get(session_id) if session_id else None

    def _initialize(self, request: dict[str, Any], *, authorization: str = "") -> RouterReply:
        backend_name = self._primary_backend_name()
        response = self._forward_raw(request, backend_name=backend_name, backend_session_id="", authorization=authorization)
        router_session_id = secrets.token_hex(16)
        session = RouterSession(id=router_session_id, initialize_request=request, authorization=authorization)
        if response.session_id:
            session.backend_sessions[backend_name] = response.session_id
        self._sessions[router_session_id] = session
        return RouterReply(response.payload, session_id=router_session_id)

    def _ensure_backend_session(self, backend_name: str, session: RouterSession | None) -> str:
        if session is None:
            return ""
        if backend_name in session.backend_sessions:
            return session.backend_sessions[backend_name]
        response = self._forward_raw(
            session.initialize_request,
            backend_name=backend_name,
            backend_session_id="",
            authorization=session.authorization,
        )
        if response.session_id:
            session.backend_sessions[backend_name] = response.session_id
        return session.backend_sessions.get(backend_name, "")

    def _forward_raw(
        self,
        request: dict[str, Any],
        *,
        backend_name: str,
        backend_session_id: str = "",
        authorization: str = "",
    ) -> BackendResponse:
        client = self._backend_client(backend_name)
        try:
            response = client.request(request, session_id=backend_session_id, authorization=authorization)
        except TypeError:
            response = client.request(request)
        return self._normalize_backend_response(response)

    def _forward(self, request: dict[str, Any], *, backend_name: str, session_id: str = "") -> dict[str, Any]:
        session = self._session(session_id)
        backend_session_id = self._ensure_backend_session(backend_name, session)
        response = self._forward_raw(
            request,
            backend_name=backend_name,
            backend_session_id=backend_session_id,
            authorization=session.authorization if session else "",
        ).payload
        if not isinstance(response, dict):
            return jsonrpc_error(request.get("id"), JSONRPC_INVALID_REQUEST, "Backend returned invalid response")
        return response

    def _backend_tools_list(self, backend_name: str, *, session_id: str = "", request_id: Any = "__router_tools_list__") -> dict[str, Any]:
        response = self._forward(
            {"jsonrpc": "2.0", "id": request_id, "method": "tools/list", "params": {}},
            backend_name=backend_name,
            session_id=session_id,
        )
        if not isinstance(response, dict):
            raise ValueError("backend tools/list returned non-object response")
        return response

    def _tools_list(self, request: dict[str, Any], *, session_id: str = "") -> dict[str, Any]:
        all_tools: list[dict[str, Any]] = []
        tool_backend_cache: dict[str, str] = {}
        base_response: dict[str, Any] | None = None
        for backend_name in self._profile_backend_names():
            response = self._backend_tools_list(backend_name, session_id=session_id, request_id=request.get("id"))
            if base_response is None:
                base_response = response
            for tool in filter_tools(extract_tools_from_response(response), self.config.profile):
                tool_name = str(tool.get("name") or "")
                if not tool_name or tool_name in tool_backend_cache:
                    continue
                tool_copy = dict(tool)
                meta = dict(tool_copy.get("_meta") or {})
                meta["mcp_router"] = {"backend": backend_name, "profile": self.profile_name}
                tool_copy["_meta"] = meta
                all_tools.append(tool_copy)
                tool_backend_cache[tool_name] = backend_name
                if self.config.profile.max_tools is not None and len(all_tools) >= self.config.profile.max_tools:
                    break
            if self.config.profile.max_tools is not None and len(all_tools) >= self.config.profile.max_tools:
                break
        self._allowed_tool_cache = frozenset(tool_backend_cache)
        self._tool_backend_cache = tool_backend_cache
        session = self._session(session_id)
        if session is not None:
            session.tool_backend_cache = tool_backend_cache
        response = base_response or {"jsonrpc": "2.0", "id": request.get("id"), "result": {}}
        response = dict(response)
        response["id"] = request.get("id")
        return replace_tools_in_response(response, all_tools)

    def _allowed_tool_names(self, *, session_id: str = "") -> frozenset[str]:
        if self._allowed_tool_cache is None:
            response = self._tools_list({"jsonrpc": "2.0", "id": "__router_cache__", "method": "tools/list", "params": {}}, session_id=session_id)
            self._allowed_tool_cache = frozenset(str(tool.get("name") or "") for tool in extract_tools_from_response(response))
        return self._allowed_tool_cache

    def _backend_for_tool(self, tool: str, *, session_id: str = "") -> str:
        session = self._session(session_id)
        if session is not None and tool in session.tool_backend_cache:
            return session.tool_backend_cache[tool]
        if tool in self._tool_backend_cache:
            return self._tool_backend_cache[tool]
        self._tools_list({"jsonrpc": "2.0", "id": "__router_cache__", "method": "tools/list", "params": {}}, session_id=session_id)
        session = self._session(session_id)
        if session is not None and tool in session.tool_backend_cache:
            return session.tool_backend_cache[tool]
        if tool in self._tool_backend_cache:
            return self._tool_backend_cache[tool]
        raise ToolNotAllowedError(f"tool backend is not allowed or not found: {tool}", data={"tool": tool, "profile": self.profile_name})

    def _tools_call(self, request: dict[str, Any], *, session_id: str = "") -> dict[str, Any]:
        params = request.get("params") or {}
        tool = str(params.get("name") or "")
        validate_tool_allowed(tool, self._allowed_tool_names(session_id=session_id), self.config.profile)
        validate_sandbox_policy(tool, params.get("arguments") or {}, self.config.profile)
        return self._forward(request, backend_name=self._backend_for_tool(tool, session_id=session_id), session_id=session_id)
