"""Smoke test RACB and capability routing through a real MCP transport."""

from __future__ import annotations

import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main() -> None:
    url = os.getenv("RACB_MCP_URL", "http://127.0.0.1:18112/mcp")
    headers = {}
    if os.getenv("MCP_API_KEY"):
        headers["X-API-Key"] = os.environ["MCP_API_KEY"]
    async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            expected = {
                "route_mcp_tools",
                "ack_agent_message",
                "update_ops_task_state",
                "manage_coordination_lock",
                "migrate_racb_records",
                "product_intelligence",
            }
            missing = sorted(expected - names)
            if missing:
                raise AssertionError(f"missing RACB tools: {missing}")

            quoteops_tools = sorted(name for name in names if name.startswith("quoteops_"))
            if len(quoteops_tools) != 15:
                raise AssertionError(
                    f"expected 15 QuoteOps tools, found {len(quoteops_tools)}: {quoteops_tools}"
                )

            route = await session.call_tool(
                "route_mcp_tools",
                {
                    "title": "Coordinar agentes y bloquear módulo",
                    "granted_scopes": ["ralfia:read", "ralfia:write", "ralfia:agents"],
                },
            )
            payload = route.structuredContent or {}
            if payload.get("profile") != "coordination" or payload.get("tool_count") != 10:
                raise AssertionError(f"unexpected route: {payload}")

            migration = await session.call_tool("migrate_racb_records", {"dry_run": True, "limit": 10})
            migration_payload = migration.structuredContent or {}
            if migration_payload.get("dry_run") is not True:
                raise AssertionError(f"migration was not dry-run: {migration_payload}")

            product_route = await session.call_tool(
                "route_mcp_tools",
                {
                    "title": "Buscar producto de proveedor en catálogo PDF",
                    "granted_scopes": ["ralfia:read", "ralfia:write"],
                },
            )
            product_route_payload = product_route.structuredContent or {}
            if product_route_payload.get("profile") != "product_catalog":
                raise AssertionError(f"unexpected product route: {product_route_payload}")

            product_search = await session.call_tool(
                "product_intelligence",
                {"action": "search", "payload": {"required_capabilities": ["qr"], "limit": 3}},
            )
            product_search_payload = product_search.structuredContent or {}
            if product_search_payload.get("ok") is not True:
                raise AssertionError(f"product search failed: {product_search_payload}")

            quoteops_route = await session.call_tool(
                "route_mcp_tools",
                {
                    "title": "Crear y completar cotizacion con QuoteOps",
                    "requested_profile": "quoteops",
                    "granted_scopes": ["ralfia:read", "ralfia:write"],
                },
            )
            quoteops_route_payload = quoteops_route.structuredContent or {}
            if (
                quoteops_route_payload.get("profile") != "quoteops"
                or quoteops_route_payload.get("tool_count") != 15
            ):
                raise AssertionError(f"unexpected QuoteOps route: {quoteops_route_payload}")

            output = {
                "ok": True,
                "tool_count": len(names),
                "racb_tools": sorted(expected),
                "profile": payload.get("profile"),
                "profile_tool_count": payload.get("tool_count"),
                "migration_dry_run": migration_payload.get("dry_run"),
                "product_profile": product_route_payload.get("profile"),
                "product_search_count": product_search_payload.get("count"),
                "quoteops_profile": quoteops_route_payload.get("profile"),
                "quoteops_tool_count": len(quoteops_tools),
            }
            if os.getenv("MCP_SMOKE_DUMP_TOOLS") == "1":
                output["tool_names"] = sorted(names)
            print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
