"""FastMCP transform: inject MCP tool annotations on tools/list."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from mcp.types import ToolAnnotations
from fastmcp.server.transforms import Transform

from inneros_core_runtime.mcp_tool_annotations import annotations_for_tool

if TYPE_CHECKING:
    from fastmcp.tools.base import Tool


class ToolAnnotationTransform(Transform):
    """Apply readOnlyHint / destructiveHint / openWorldHint from central policy."""

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        updated: list[Tool] = []
        for tool in tools:
            hints = annotations_for_tool(tool.name)
            ann = ToolAnnotations(
                readOnlyHint=hints.get("readOnlyHint"),
                destructiveHint=hints.get("destructiveHint"),
                openWorldHint=hints.get("openWorldHint"),
            )
            if tool.annotations:
                merged = tool.annotations.model_copy(
                    update={
                        k: v
                        for k, v in {
                            "readOnlyHint": ann.readOnlyHint,
                            "destructiveHint": ann.destructiveHint,
                            "openWorldHint": ann.openWorldHint,
                        }.items()
                        if v is not None
                    }
                )
                updated.append(tool.model_copy(update={"annotations": merged}))
            else:
                updated.append(tool.model_copy(update={"annotations": ann}))
        return updated
