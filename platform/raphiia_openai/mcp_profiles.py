"""Compatibility shim for MCP profile definitions.

The canonical MCP profile registry lives in inneros_core_runtime.mcp_profiles.
Keeping a second copy here caused profile drift between diagnostics/routing and
FastMCP tools/list projection. Re-export the canonical definitions so every
caller observes the same profile pin and tool set.
"""

from inneros_core_runtime.mcp_profiles import (  # noqa: F401
    PROFILES,
    PROFILES_VERSION,
    get_profile,
    list_profiles,
    validate_profiles,
)

__all__ = [
    "PROFILES",
    "PROFILES_VERSION",
    "get_profile",
    "list_profiles",
    "validate_profiles",
]
