#!/usr/bin/env python3
"""Start the canonical InnerOS MCP runtime.

This tiny launcher preserves the systemd unit contract while keeping all server
configuration and startup behavior in ``inneros_core_runtime.mcp_server``.
"""

from __future__ import annotations

import os

from inneros_core_runtime import mcp_server as server
from inneros_core_runtime.mcp_tool_annotation_transform import ToolAnnotationTransform


if __name__ == "__main__":
    runtime_profile = os.getenv("MCP_TOOL_PROFILE", "").strip().lower()
    if runtime_profile:
        profile_info = server._apply_runtime_tool_profile(runtime_profile)
        server.mongo_store.log_sync(
            "mcp_profile_startup",
            host=server.MCP_HOST,
            port=server.MCP_PORT,
            **profile_info,
        )

    server.mcp.add_transform(ToolAnnotationTransform())
    server.mongo_store.log_sync(
        "mcp_startup",
        host=server.MCP_HOST,
        port=server.MCP_PORT,
    )
    server.mcp.run(
        transport="streamable-http",
        host=server.MCP_HOST,
        port=server.MCP_PORT,
        path="/mcp",
        middleware=[
            server.StarletteMiddleware(server.McpSmallOAuthDiscoveryMiddleware)
        ],
    )
