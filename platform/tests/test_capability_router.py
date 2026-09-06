from __future__ import annotations

from raphiia_openai import capability_router, mcp_profiles


def test_default_route_is_compact_bootstrap_for_chatgpt() -> None:
    result = capability_router.route_tools(
        title="Necesito saber que puedo hacer en el MCP",
        body="Arranca y dime que perfiles usar.",
        for_model="small-chatgpt-session",
    )

    assert result["ok"] is True
    assert result["profile"] == "chatgpt_compact"
    assert result["tool_count"] <= 12
    assert result["recommended_next_call"]["tool"] == "route_mcp_tools"
    assert "route_mcp_tools" in result["tools"]
    assert "get_coordination_live" in result["tools"]


def test_development_intent_routes_to_owner_dev_without_global_catalog() -> None:
    result = capability_router.route_tools(
        title="P0 reparar Workforce repo_not_inferred",
        body="Usa worktree, github branch, npm ci, pytest, commit y dev swarm scheduler.",
        max_tools=18,
    )

    assert result["ok"] is True
    assert result["profile"] == "owner_dev"
    assert result["tool_count"] == 18
    assert any(item["reason"] == "client_tool_budget" for item in result["excluded"])
    assert "local_exec_inspect_repo" in result["tools"]
    assert "local_exec_run_command_allowlisted" not in result["tools"]


def test_email_and_business_messages_do_not_pollute_development_route() -> None:
    result = capability_router.route_tools(
        title="Enviar mensaje de WhatsApp al grupo",
        body="Prepara comunicacion y correo para contactos; no es tarea de desarrollo.",
    )

    assert result["ok"] is True
    assert result["profile"] == "communications"
    assert "dev_swarm_scheduler_tick" not in result["tools"]
    assert "local_exec_run_command_allowlisted" not in result["tools"]


def test_small_model_budget_caps_large_explicit_profile() -> None:
    result = capability_router.route_tools(
        title="Desarrollo local",
        requested_profile="owner_dev",
        for_model="tiny-local-model",
    )

    assert result["ok"] is True
    assert result["profile"] == "owner_dev"
    assert result["tool_count"] == 8
    assert result["max_tools"] == 8
    assert result["profile_max_tools"] == mcp_profiles.PROFILES["owner_dev"]["max_tools"]
    assert any(item["reason"] == "client_tool_budget" for item in result["excluded"])


def test_scope_and_risk_filters_still_apply_before_budget() -> None:
    missing_scope = capability_router.route_tools(
        title="Ejecutar reparacion",
        requested_profile="local_self_repair",
        granted_scopes=["ralfia:read"],
        max_tools=40,
    )
    risk_block = capability_router.route_tools(
        title="Ejecutar reparacion",
        requested_profile="local_self_repair",
        max_risk="low",
        max_tools=40,
    )

    assert missing_scope["ok"] is True
    assert missing_scope["tools"]
    assert "missing_scope" in {item["reason"] for item in missing_scope["excluded"]}
    assert risk_block["ok"] is True
    assert "risk_exceeds_ceiling" in {item["reason"] for item in risk_block["excluded"]}
    assert "local_exec_run_command_allowlisted" not in missing_scope["tools"]


def test_profile_registry_validates_after_router_changes() -> None:
    validation = mcp_profiles.validate_profiles()
    errors_by_profile = {}
    for error in validation["errors"]:
        errors_by_profile.setdefault(error["profile"], []).append(error)

    assert "chatgpt_compact" not in errors_by_profile
    assert "owner_dev" not in errors_by_profile
    assert "local_self_repair" not in errors_by_profile


def test_unrelated_stale_profile_does_not_block_valid_route() -> None:
    result = capability_router.route_tools(
        title="Arranque de ChatGPT",
        requested_profile="chatgpt_compact",
    )

    assert result["ok"] is True
    assert result["profile"] == "chatgpt_compact"
    assert result["registry_ok"] is False
    assert result["registry_error_count"] > 0
