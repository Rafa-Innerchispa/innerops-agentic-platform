#!/usr/bin/env python3
"""Verify real MCP transport failover from a dead primary to AMD canary."""

from __future__ import annotations

import json
import socket
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:18113/mcp"


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def rpc(method: str, params: dict[str, Any] | None = None, call_id: int = 1) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": call_id, "method": method, "params": params or {}}
    request = urllib.request.Request(
        BASE,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def call_tool(name: str, arguments: dict[str, Any], call_id: int) -> dict[str, Any]:
    return rpc("tools/call", {"name": name, "arguments": arguments}, call_id)


def main() -> None:
    require(listening(8102), "Intel production MCP 8102 is not listening")
    require(not listening(18999), "deliberately unavailable primary unexpectedly exists")
    require(listening(18212), "AMD SSH tunnel 18212 is not listening")
    require(listening(18113), "failover gateway 18113 is not listening")

    initialized = rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "p0-failover-smoke", "version": "1.0"},
        },
        1,
    )
    require("result" in initialized, f"initialize did not fail over: {initialized}")

    listed = rpc("tools/list", {}, 2)
    tools = listed.get("result", {}).get("tools", [])
    require(1 <= len(tools) <= 15, f"compact contract invalid: {len(tools)}")

    invoked = call_tool(
        "invoke_capability",
        {"capability_id": "mcp_version", "arguments": {}},
        3,
    )
    require("result" in invoked, f"mcp_version did not fail over: {invoked}")

    denied = call_tool(
        "invoke_capability",
        {
            "capability_id": "create_agent_message",
            "arguments": {
                "target_agent": "nobody",
                "title": "must-not-run",
                "body": "must-not-run"
            },
        },
        4,
    )
    require(denied.get("error", {}).get("code") == -32003, f"unlisted mutation was not denied: {denied}")

    require(listening(8102), "production MCP changed during failover smoke")
    require(not listening(18999), "dead-primary assumption changed during smoke")

    print(json.dumps({
        "ok": True,
        "mode": "real_transport_mcp_failover_canary",
        "primary": "127.0.0.1:18999_deliberately_unavailable",
        "secondary": "127.0.0.1:18212_ssh_tunnel_to_amd_canary",
        "gateway": "127.0.0.1:18113",
        "initialize_failover": "pass",
        "tools_list_failover": "pass",
        "safe_tool_call_failover": "pass",
        "unlisted_mutation": "denied_fail_closed",
        "exposed_tool_count": len(tools),
        "production_port_8102": "listening_untouched",
        "production_deploy": False,
        "production_restart": False,
        "workflow_started": False,
    }, indent=2))


if __name__ == "__main__":
    main()
