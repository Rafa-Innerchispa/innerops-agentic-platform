"""Read-only preflight of the canonical router dependencies."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def test_canonical_router_dependencies():
    from inneros_core_runtime import mcp_profiles, capability_router
    from inneros_core_runtime.mcp_catalog import tool_catalog
    result = capability_router.route_tools(title="router preflight", requested_profile="chatgpt_compact", granted_scopes=["ralfia:read"], max_risk="low")
    print("CANONICAL_PREFLIGHT", result)
    print("CATALOG_METADATA", {n: tool_catalog.TOOL_DEFINITIONS.get(n) for n in ["mcp_version","local_exec_write_file","local_exec_run_command_allowlisted"]})
    assert result["ok"], result
