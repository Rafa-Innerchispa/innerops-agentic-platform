#!/usr/bin/env python3
"""Protocol smoke for the isolated MCP Small gateway. Never mutates production."""

from __future__ import annotations

import json
import socket
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:18112/mcp"


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def rpc(method: str, params: dict[str, Any] | None = None, *, headers: dict[str, str] | None = None, call_id: int = 1) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": call_id, "method": method, "params": params or {}}
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        BASE,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def tool_call(name: str, arguments: dict[str, Any], *, headers: dict[str, str] | None = None, call_id: int = 10) -> dict[str, Any]:
    return rpc(
        "tools/call",
        {"name": name, "arguments": arguments},
        headers=headers,
        call_id=call_id,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def main() -> None:
    require(listening(8102), "production MCP port 8102 is not listening")
    require(listening(18102), "monolith canary port 18102 is not listening")
    require(listening(18112), "MCP Small canary port 18112 is not listening")

    initialized = rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "p0-small-smoke", "version": "1.0"},
        },
        call_id=1,
    )
    require("result" in initialized, f"initialize failed: {initialized}")

    listed = rpc("tools/list", call_id=2)
    tools = listed.get("result", {}).get("tools", [])
    names = [tool.get("name") for tool in tools]
    require(1 <= len(names) <= 15, f"compact contract size invalid: {len(names)}")
    for required in ("search_capabilities", "describe_capability", "invoke_capability"):
        require(required in names, f"missing broker tool {required}")

    searched = tool_call("search_capabilities", {"query": "mcp", "limit": 5}, call_id=3)
    require("result" in searched, f"search_capabilities failed: {searched}")

    described = tool_call("describe_capability", {"capability_id": "mcp_version"}, call_id=4)
    require("result" in described, f"describe_capability failed: {described}")

    invoked = tool_call(
        "invoke_capability",
        {"capability_id": "mcp_version", "arguments": {}},
        call_id=5,
    )
    require("result" in invoked, f"allowlisted invocation failed: {invoked}")

    denied_broker = tool_call(
        "invoke_capability",
        {"capability_id": "local_exec_run_command_allowlisted", "arguments": {"command": "true"}},
        call_id=6,
    )
    require(denied_broker.get("error", {}).get("code") == -32003, f"broker bypass was not denied: {denied_broker}")

    denied_direct = tool_call(
        "local_exec_run_command_allowlisted",
        {"command": "true"},
        call_id=7,
    )
    require(denied_direct.get("error", {}).get("code") == -32003, f"direct bypass was not denied: {denied_direct}")

    denied_admin = tool_call(
        "mcp_version",
        {},
        headers={"X-MCP-Profile": "profile_admin", "X-MCP-Admin-Secret": "not-valid"},
        call_id=8,
    )
    require(denied_admin.get("error", {}).get("code") == -32003, f"admin profile was not denied: {denied_admin}")

    require(listening(8102), "production MCP port 8102 changed during smoke")

    print(json.dumps({
        "ok": True,
        "mode": "isolated_mcp_small_gateway_smoke",
        "production_port_8102": "listening_untouched",
        "monolith_canary_port_18102": "listening",
        "small_canary_port_18112": "listening",
        "exposed_tool_count": len(names),
        "exposed_tools": names,
        "search_capabilities": "pass",
        "describe_capability": "pass",
        "allowlisted_invoke": "pass",
        "unlisted_broker_invoke": "denied_fail_closed",
        "unlisted_direct_invoke": "denied_fail_closed",
        "unauthorized_admin_profile": "denied_fail_closed",
        "production_deploy": False,
        "production_restart": False,
    }, indent=2))


if __name__ == "__main__":
    main()
