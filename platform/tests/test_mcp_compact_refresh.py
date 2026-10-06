from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import mcp.types as mt

from inneros_core_runtime.mcp_compact_refresh import CompactProfileRefreshMiddleware, record_compact_surface


def test_initialize_advertises_list_changed_on_compact_plane(monkeypatch):
    monkeypatch.setenv("MCP_TOOL_PROFILE", "chatgpt_compact")
    record_compact_surface(profile_pin="1.4.8:chatgpt_compact:abc", profiles_version="1.4.8", tool_count=25)
    mw = CompactProfileRefreshMiddleware()
    base = mt.InitializeResult(
        protocolVersion="2024-11-05",
        capabilities=mt.ServerCapabilities(),
        serverInfo=mt.Implementation(name="test", version="1"),
    )
    call_next = AsyncMock(return_value=base)
    ctx = MagicMock()

    async def _run():
        return await mw.on_initialize(ctx, call_next)

    result = asyncio.run(_run())
    assert result.capabilities.tools is not None
    assert result.capabilities.tools.listChanged is True
    assert result.meta.get("inneros_compact_tool_count") == 25
