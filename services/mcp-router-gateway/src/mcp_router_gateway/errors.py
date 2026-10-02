from __future__ import annotations

from typing import Any


JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_INTERNAL_ERROR = -32603
TOOL_NOT_ALLOWED = -32060
SANDBOX_POLICY_DENIED = -32061
BACKEND_ERROR = -32070


class RouterError(RuntimeError):
    code = JSONRPC_INTERNAL_ERROR
    name = "RouterError"

    def __init__(self, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.data = data or {}


class ToolNotAllowedError(RouterError):
    code = TOOL_NOT_ALLOWED
    name = "ToolNotAllowedError"


class SandboxPolicyError(RouterError):
    code = SANDBOX_POLICY_DENIED
    name = "SandboxPolicyError"


class BackendError(RouterError):
    code = BACKEND_ERROR
    name = "BackendError"


def jsonrpc_error(request_id: Any, code: int, message: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def router_error_response(request_id: Any, exc: RouterError) -> dict[str, Any]:
    return jsonrpc_error(
        request_id,
        exc.code,
        exc.name,
        data={"message": str(exc), **exc.data},
    )

