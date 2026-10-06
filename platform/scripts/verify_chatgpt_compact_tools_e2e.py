#!/usr/bin/env python3
"""E2E: chatgpt_compact MCP must list exactly 25 tools (incl. capability_*)."""

from __future__ import annotations

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from inneros_core_runtime import mcp_profiles

CAPABILITY_TOOLS = (
    "capability_search",
    "capability_describe",
    "capability_invoke",
    "capability_execution",
)


async def probe(url: str, api_key: str) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"X-API-Key": api_key}
    async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            profile = set(mcp_profiles.PROFILES["chatgpt_compact"]["tools"])
            missing_profile = sorted(profile - names)
            missing_capability = sorted(set(CAPABILITY_TOOLS) - names)
            return {
                "ok": len(names) == 25 and not missing_profile and not missing_capability,
                "url": url,
                "listed": len(names),
                "missing_from_profile": missing_profile,
                "missing_capability_tools": missing_capability,
                "names": sorted(names),
            }


def main() -> int:
    url = os.getenv("COORD_E2E_MCP_URL", "http://127.0.0.1:8112/mcp").strip()
    api_key = os.getenv("MCP_API_KEY", "").strip()
    if not api_key:
        print(json.dumps({"ok": False, "error": "MCP_API_KEY unset"}))
        return 1
    try:
        result = asyncio.run(probe(url, api_key))
    except Exception as exc:
        print(json.dumps({"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
