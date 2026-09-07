import sys
import types
from pathlib import Path


PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

fastmcp = types.ModuleType("fastmcp")
fastmcp_exceptions = types.ModuleType("fastmcp.exceptions")
fastmcp_dependencies = types.ModuleType("fastmcp.server.dependencies")
fastmcp_middleware = types.ModuleType("fastmcp.server.middleware")
fastmcp_server = types.ModuleType("fastmcp.server")


class ToolError(Exception):
    pass


class Middleware:
    pass


class MiddlewareContext:
    pass


fastmcp_exceptions.ToolError = ToolError
fastmcp_dependencies.get_http_headers = lambda include=None: {}
fastmcp_dependencies.get_http_request = lambda: (_ for _ in ()).throw(RuntimeError("no request"))
fastmcp_middleware.Middleware = Middleware
fastmcp_middleware.MiddlewareContext = MiddlewareContext
sys.modules.setdefault("fastmcp", fastmcp)
sys.modules.setdefault("fastmcp.exceptions", fastmcp_exceptions)
sys.modules.setdefault("fastmcp.server", fastmcp_server)
sys.modules.setdefault("fastmcp.server.dependencies", fastmcp_dependencies)
sys.modules.setdefault("fastmcp.server.middleware", fastmcp_middleware)

from inneros_core_runtime import mcp_profiles
from inneros_core_runtime.auth_middleware import _token_profile_guard


def test_notion_team_profile_contract_is_valid() -> None:
    result = mcp_profiles.validate_profiles()

    assert result["ok"], result["errors"]
    assert "notion_team" in mcp_profiles.PROFILES


def test_profile_guard_allows_notion_team_tools() -> None:
    token_doc = {"mcp_profile": "notion_team"}

    assert _token_profile_guard(token_doc, "get_coordination_live")["ok"] is True
    assert _token_profile_guard(token_doc, "local_exec_create_worktree")["ok"] is True
    assert _token_profile_guard(token_doc, "notion_push_doc")["ok"] is True


def test_profile_guard_blocks_tools_outside_notion_team() -> None:
    token_doc = {"mcp_profile": "notion_team"}

    result = _token_profile_guard(token_doc, "cloudflare_dns_delete")

    assert result["ok"] is False
    assert result["error"] == "tool_not_allowed_for_profile"
