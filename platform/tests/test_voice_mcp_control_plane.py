import sys
from pathlib import Path


PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from raphiia_openai import voice_mcp_executor


OWNER = {"username": "rlopez", "email": "rlopez@innerchispa.us", "is_admin": True}
OPERATOR = {"username": "operador", "email": "ops@example.com", "is_admin": False}


def _tools_for(text: str, user: dict = OWNER) -> list[tuple[str, dict]]:
    return voice_mcp_executor.detect_tool_calls(user, text)


def test_voice_quotes_route_to_compact_quoter_profile() -> None:
    calls = _tools_for("necesito hacer una cotizacion para un cliente de camaras y red")

    routed = [args for name, args in calls if name == "route_mcp_tools"]

    assert routed
    assert routed[0]["requested_profile"] == "quoter"
    assert routed[0]["for_model"] == "small"
    assert routed[0]["max_tools"] <= 12


def test_voice_development_routes_to_owner_dev_without_shell() -> None:
    calls = _tools_for("programa una app nueva, crea el repo en GitHub y haz commit")

    assert calls[0][0] == "route_mcp_tools"
    assert calls[0][1]["requested_profile"] == "owner_dev"
    assert "shell" not in {name for name, _ in calls}


def test_voice_operator_does_not_get_owner_dev_route() -> None:
    calls = _tools_for("programa una app nueva y haz commit", user=OPERATOR)

    assert all(name != "route_mcp_tools" for name, _args in calls)


def test_voice_home_dmx_keeps_direct_allowlisted_control() -> None:
    calls = _tools_for("pon los tachos en morado")

    assert calls[0][0] == "dmx_set_scene"
    assert calls[0][1]["target"] == "tachos"
    assert calls[0][1]["color"] == "morado_uv"


def test_voice_mcp_policy_can_hide_tool_list_for_public_health() -> None:
    public = voice_mcp_executor.mcp_policy_summary(OWNER, include_tools=False)
    private = voice_mcp_executor.mcp_policy_summary(OWNER, include_tools=True)

    assert public["profile"] == "voice_owner_compact"
    assert public["strategy"] == "compact_tool_surface_with_capability_router"
    assert public["full_catalog_access_path"] == "route_mcp_tools"
    assert "visible_tools" not in public
    assert "visible_tools" in private
