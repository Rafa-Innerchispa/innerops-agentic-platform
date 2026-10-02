from __future__ import annotations

from typing import Any

from pathlib import Path

from mcp_router_gateway.config import BackendTarget, RouterConfig, SandboxPolicy, ToolProfile, load_profiles
from mcp_router_gateway.router import McpRouter


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any] | list[Any]] = []
        self.tools = [
            {"name": "git_status", "description": "status", "inputSchema": {"type": "object"}},
            {"name": "docker_ps", "description": "containers", "inputSchema": {"type": "object"}},
            {"name": "fs_read", "description": "read", "inputSchema": {"type": "object"}},
            {"name": "secret_dump", "description": "nope", "inputSchema": {"type": "object"}},
        ]

    def request(self, payload: dict[str, Any] | list[Any]) -> dict[str, Any] | list[Any]:
        self.calls.append(payload)
        if isinstance(payload, dict) and payload.get("method") == "tools/list":
            return {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"tools": self.tools}}
        if isinstance(payload, dict) and payload.get("method") == "tools/call":
            return {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"ok": True, "echo": payload["params"]["name"]}}
        return {"jsonrpc": "2.0", "id": payload.get("id") if isinstance(payload, dict) else None, "result": {"ok": True}}


def make_router(profile: ToolProfile) -> McpRouter:
    config = RouterConfig(
        host="127.0.0.1",
        port=8001,
        active_profile=profile.name,
        default_backend="default",
        backends={"default": BackendTarget(name="default", url="http://backend.invalid")},
        profiles={profile.name: profile},
    )
    return McpRouter(config, backend=FakeBackend())  # type: ignore[arg-type]


def test_tools_list_filters_by_profile_prefixes() -> None:
    router = make_router(ToolProfile(name="profile_coding", prefixes=("git_", "docker_", "fs_"), max_tools=25))
    response = router.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})

    tools = response["result"]["tools"]  # type: ignore[index]
    assert [tool["name"] for tool in tools] == ["git_status", "docker_ps", "fs_read"]


def test_tools_call_rejects_unlisted_tool() -> None:
    router = make_router(ToolProfile(name="profile_coding", prefixes=("git_",), max_tools=25))
    response = router.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "secret_dump", "arguments": {}}})

    assert response["error"]["message"] == "ToolNotAllowedError"  # type: ignore[index]
    assert response["error"]["code"] == -32060  # type: ignore[index]


def test_tools_call_forwards_allowed_tool() -> None:
    router = make_router(ToolProfile(name="profile_coding", prefixes=("git_",), max_tools=25))
    response = router.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "git_status", "arguments": {}}})

    assert response["result"]["ok"] is True  # type: ignore[index]
    assert response["result"]["echo"] == "git_status"  # type: ignore[index]


def test_session_initialize_then_tools_list() -> None:
    router = make_router(ToolProfile(name="profile_coding", prefixes=("git_", "docker_"), max_tools=25))
    init = router.handle_with_session(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        }
    )

    assert init.session_id
    response = router.handle_with_session(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session_id=init.session_id,
    ).payload

    tools = response["result"]["tools"]  # type: ignore[index]
    assert [tool["name"] for tool in tools] == ["git_status", "docker_ps"]
    assert tools[0]["_meta"]["mcp_router"]["backend"] == "default"


def test_sandbox_blocks_path_outside_workspace() -> None:
    router = make_router(
        ToolProfile(
            name="profile_fs",
            prefixes=("fs_",),
            sandbox=SandboxPolicy(allowed_roots=("/workspace",), read_only_required_for_prefixes=("fs_",)),
        )
    )
    response = router.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "fs_read", "arguments": {"path": "/etc/passwd"}},
        }
    )

    assert response["error"]["message"] == "SandboxPolicyError"  # type: ignore[index]
    assert response["error"]["code"] == -32061  # type: ignore[index]


def test_load_profiles_from_json() -> None:
    path = Path(__file__).resolve().parents[1] / "profiles.json"
    default_profile, default_backend, backends, profiles = load_profiles(path)

    assert default_profile == "chatgpt_compact"
    assert default_backend == "inneros_compact"
    assert "inneros_compact" in backends
    assert "coding" in profiles
    assert profiles["admin"].allow_all is True
