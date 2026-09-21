"""Standalone Cognee MCP surface for InnerOS.

This server deliberately exposes only Cognee capabilities so it can be
connected independently from the full Ralphi IA MCP.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from raphiia_openai import cognee_provider


mcp = FastMCP(
    "InnerOS Cognee",
    instructions=(
        "Reusable Cognee memory provider for InnerOS. "
        "Credentials stay server-side. Use status/preflight before live memory calls."
    ),
)


@mcp.tool
async def cognee_status() -> dict[str, Any]:
    """Return safe provider readiness without exposing credentials."""
    return await cognee_provider.status()


@mcp.tool
async def cognee_preflight(live: bool = False) -> dict[str, Any]:
    """Validate configuration; live=true performs a bounded recall probe."""
    return await cognee_provider.preflight(live=live)


@mcp.tool
async def cognee_memory_search(
    query: str,
    limit: int = 8,
    dataset: str | None = None,
    only_context: bool = True,
) -> dict[str, Any]:
    """Search structured Cognee memory."""
    return await cognee_provider.memory_search(
        query=query,
        limit=limit,
        dataset=dataset,
        only_context=only_context,
    )


@mcp.tool
async def cognee_remember(
    text: str,
    metadata: dict[str, Any] | None = None,
    dataset: str | None = None,
    self_improvement: bool = False,
) -> dict[str, Any]:
    """Persist a verified memory into Cognee."""
    return await cognee_provider.remember(
        text=text,
        metadata=metadata,
        dataset=dataset,
        self_improvement=self_improvement,
    )


@mcp.tool
async def cognee_knowledge_graph(
    query: str,
    limit: int = 12,
    dataset: str | None = None,
) -> dict[str, Any]:
    """Retrieve graph-oriented context from Cognee."""
    return await cognee_provider.knowledge_graph(
        query=query,
        limit=limit,
        dataset=dataset,
    )
