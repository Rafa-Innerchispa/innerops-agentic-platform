#!/usr/bin/env python3
"""Read-only HTTP smoke probe for the isolated P0 MCP canary."""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:18102"


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"{path}: HTTP {response.status}")
        return json.load(response)


def main() -> None:
    ready = get_json("/ready")
    version = get_json("/version")
    capabilities = get_json("/capabilities")

    if not ready.get("ok"):
        raise SystemExit("FAIL: /ready did not confirm Mongo connectivity")
    tool_count = int(version.get("tool_count") or 0)
    if not 1 <= tool_count <= 12:
        raise SystemExit(f"FAIL: projected tool_count outside safe compact range: {tool_count}")
    if "contifico_analytics" not in (capabilities.get("profiles") or []):
        raise SystemExit("FAIL: expected compact profile is not advertised")

    print(json.dumps({
        "ok": True,
        "mode": "isolated_mcp_http_smoke",
        "bind": "127.0.0.1:18102",
        "ready": ready,
        "version": version,
        "projected_tool_count": tool_count,
        "production_deploy": False,
        "production_restart": False,
        "nats_enabled": False,
        "workflow_started": False,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
