"""Static contracts for the import-safe MCP systemd launcher."""

from pathlib import Path

from inneros_core_runtime.mcp_tool_annotations import classify_tool


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PLATFORM_ROOT / "scripts" / "run_mcp_runtime.py"


def test_launcher_imports_server_under_its_canonical_module_name() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "from inneros_core_runtime import mcp_server as server" in source
    assert "Path(__file__).resolve().parents[1]" in source
    assert "sys.path.insert(0, str(PLATFORM_ROOT))" in source
    assert "runpy.run_module" not in source


def test_systemd_units_use_import_safe_launcher() -> None:
    units = (
        PLATFORM_ROOT / "systemd" / "user" / "ralfia-mcp.service",
        PLATFORM_ROOT / "deploy" / "systemd" / "ralfia-mcp-profile@.service",
    )
    for unit in units:
        source = unit.read_text(encoding="utf-8")
        assert "scripts/run_mcp_runtime.py" in source
        assert "-m inneros_core_runtime.mcp_server" not in source


def test_ide_agent_claim_tools_have_explicit_safety_classes() -> None:
    for agent in ("cursor", "codex", "antigravity", "gemini"):
        assert classify_tool(f"{agent}_list_claimable_ops_tasks") == "read"
        assert classify_tool(f"{agent}_claim_ops_task") == "destructive"
        assert classify_tool(f"{agent}_complete_ops_task") == "destructive"
        assert classify_tool(f"{agent}_owner_order") == "destructive"
