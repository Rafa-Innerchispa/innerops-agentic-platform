#!/usr/bin/env python3
"""Read-only HTTP smoke probe for the isolated P0 MCP canary."""
from __future__ import annotations

import json
import socket
import urllib.request

BASE = "http://127.0.0.1:18102"


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def get_json(path: str, timeout: float = 8) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{path}: HTTP {response.status}")
        return json.load(response)


def main() -> None:
    if not port_open(8102):
        raise SystemExit("FAIL: production MCP port 8102 is not listening")
    if not port_open(18102):
        raise SystemExit("FAIL: canary MCP port 18102 is not listening")

    ready = get_json("/ready")
    version = get_json("/version")

    if not ready.get("ok"):
        raise SystemExit("FAIL: /ready did not confirm Mongo connectivity")
    tool_count = int(version.get("tool_count") or 0)
    if not 1 <= tool_count <= 12:
        raise SystemExit(f"FAIL: projected tool_count outside safe compact range: {tool_count}")

    print(json.dumps({
        "ok": True,
        "mode": "isolated_mcp_http_smoke",
        "production_port_8102": "listening_untouched",
        "canary_port_18102": "listening",
        "ready": ready,
        "version": version,
        "projected_tool_count": tool_count,
        "production_deploy": False,
        "production_restart": False,
        "nats_enabled": False,
        "workflow_started": False,
        "note": "Heavy /capabilities fleet aggregation is intentionally excluded from the P0 liveness gate.",
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
