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

    assert "notion_team" in mcp_profiles.PROFILES
    assert "notion_operator" in mcp_profiles.PROFILES
    notion_errors = [e for e in result["errors"] if e["profile"] in {"notion_team", "notion_operator"}]
    assert notion_errors == []


def test_profile_guard_allows_notion_team_tools() -> None:
    token_doc = {"mcp_profile": "notion_team"}

    assert _token_profile_guard(token_doc, "get_coordination_live")["ok"] is True
    assert _token_profile_guard(token_doc, "local_exec_create_worktree")["ok"] is True
    assert _token_profile_guard(token_doc, "notion_push_doc")["ok"] is True
    assert _token_profile_guard(token_doc, "sync_documentation_now")["ok"] is True
    assert _token_profile_guard(token_doc, "route_agent_request")["ok"] is True
    assert _token_profile_guard(token_doc, "external_repair_agent_run_task")["ok"] is True


def test_notion_operator_allows_sync_and_supervised_runs_without_local_exec() -> None:
    token_doc = {"mcp_profile": "notion_operator"}

    assert _token_profile_guard(token_doc, "sync_documentation_now")["ok"] is True
    assert _token_profile_guard(token_doc, "documentary_state")["ok"] is True
    assert _token_profile_guard(token_doc, "get_creator_os_project_map")["ok"] is True
    assert _token_profile_guard(token_doc, "save_chatgpt_note")["ok"] is True
    assert _token_profile_guard(token_doc, "log_coordination_event")["ok"] is True
    assert _token_profile_guard(token_doc, "external_repair_agent_status")["ok"] is True
    assert _token_profile_guard(token_doc, "external_repair_run_start")["ok"] is True
    assert _token_profile_guard(token_doc, "external_repair_run_checkpoint")["ok"] is True

    denied = _token_profile_guard(token_doc, "local_exec_run_command_allowlisted")
    assert denied["ok"] is False
    assert denied["error"] == "tool_not_allowed_for_profile"


def test_profile_guard_blocks_tools_outside_notion_team() -> None:
    token_doc = {"mcp_profile": "notion_team"}

    result = _token_profile_guard(token_doc, "cloudflare_dns_delete")

    assert result["ok"] is False
    assert result["error"] == "tool_not_allowed_for_profile"
