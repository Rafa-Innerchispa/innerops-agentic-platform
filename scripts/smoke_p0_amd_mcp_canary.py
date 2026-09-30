#!/usr/bin/env python3
"""Read-only protocol smoke for the clean AMD MCP canary."""

from __future__ import annotations

import asyncio
import json
import socket
import urllib.request

from fastmcp import Client

BASE = "http://127.0.0.1:18202"
MCP_URL = f"{BASE}/mcp"


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def get_json(path: str, timeout: float = 8) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{path}: HTTP {response.status}")
        return json.load(response)


async def projected_tool_names() -> list[str]:
    async with Client(MCP_URL) as client:
        tools = await client.list_tools()
    return sorted(tool.name for tool in tools)


async def main() -> None:
    if not port_open(8102):
        raise SystemExit("FAIL: AMD production MCP port 8102 is not listening")
    if not port_open(18202):
        raise SystemExit("FAIL: AMD canary MCP port 18202 is not listening")

    ready = get_json("/ready")
    version = get_json("/version")
    tools = await projected_tool_names()

    if not ready.get("ok"):
        raise SystemExit("FAIL: /ready did not confirm isolated Mongo connectivity")
    if not 1 <= len(tools) <= 12:
        raise SystemExit(f"FAIL: AMD canary exposed {len(tools)} tools")
    required = {"mcp_version", "diagnose_mcp_session"}
    missing = sorted(required - set(tools))
    if missing:
        raise SystemExit(f"FAIL: compact diagnostic tools missing: {missing}")

    print(json.dumps({
        "ok": True,
        "mode": "isolated_amd_mcp_protocol_smoke",
        "production_port_8102": "listening_untouched",
        "amd_canary_port_18202": "listening",
        "ready": ready,
        "version": version,
        "global_catalog_tool_count": version.get("tool_count"),
        "projected_protocol_tool_count": len(tools),
        "projected_protocol_tools": tools,
        "production_deploy": False,
        "production_restart": False,
        "live_checkout_mutated": False,
        "nats_enabled": False,
        "workflow_started": False,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
