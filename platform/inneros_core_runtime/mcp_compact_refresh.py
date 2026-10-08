"""MCP Small: advertise tool-list refresh contract for chatgpt_compact clients."""

from __future__ import annotations

import os
from typing import Any

import mcp.types as mt
from fastmcp.server.middleware import Middleware, MiddlewareContext

COMPACT_PROFILE_PIN: str | None = None
COMPACT_PROFILES_VERSION: str | None = None
COMPACT_TOOL_COUNT: int | None = None


def record_compact_surface(*, profile_pin: str, profiles_version: str, tool_count: int) -> None:
    global COMPACT_PROFILE_PIN, COMPACT_PROFILES_VERSION, COMPACT_TOOL_COUNT
    COMPACT_PROFILE_PIN = profile_pin
    COMPACT_PROFILES_VERSION = profiles_version
    COMPACT_TOOL_COUNT = tool_count


def compact_refresh_metadata() -> dict[str, Any]:
    return {
        "profile": os.getenv("MCP_TOOL_PROFILE") or None,
        "profile_pin": COMPACT_PROFILE_PIN,
        "profiles_version": COMPACT_PROFILES_VERSION,
        "tool_count": COMPACT_TOOL_COUNT,
        "list_changed_advertised": _compact_plane(),
    }


def _compact_plane() -> bool:
    return os.getenv("MCP_TOOL_PROFILE", "").strip().lower() == "chatgpt_compact"


class CompactProfileRefreshMiddleware(Middleware):
    """Advertise tools.listChanged on initialize for bounded compact sessions."""

    async def on_initialize(
        self,
        context: MiddlewareContext[mt.InitializeRequest],
        call_next,
    ) -> mt.InitializeResult | None:
        result = await call_next(context)
        if not _compact_plane() or result is None:
            return result
        caps = result.capabilities
        tools_cap = caps.tools if caps and caps.tools else mt.ToolsCapability()
        if not tools_cap.listChanged:
            tools_cap = mt.ToolsCapability(listChanged=True)
            result = result.model_copy(
                update={
                    "capabilities": (caps or mt.ServerCapabilities()).model_copy(
                        update={"tools": tools_cap}
                    )
                }
            )
        meta = dict(result.meta or {})
        if COMPACT_PROFILE_PIN:
            meta["inneros_profile_pin"] = COMPACT_PROFILE_PIN
        if COMPACT_PROFILES_VERSION:
            meta["inneros_profiles_version"] = COMPACT_PROFILES_VERSION
        if COMPACT_TOOL_COUNT is not None:
            meta["inneros_compact_tool_count"] = COMPACT_TOOL_COUNT
        if meta != (result.meta or {}):
            result = result.model_copy(update={"meta": meta})
        return result
