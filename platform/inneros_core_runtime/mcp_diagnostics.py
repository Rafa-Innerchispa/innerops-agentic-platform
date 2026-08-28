"""Diagnostico vivo para MCP, catalogo y sesiones de connector."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.settings import MCP_API_KEY, MCP_DISPLAY_NAME, MCP_PUBLIC_URL, MCP_SERVER_VERSION, OAUTH_ISSUER
from raphiia_openai.mcp_catalog import tool_catalog

SERVER_VERSION = MCP_SERVER_VERSION
BRIDGE_VERSION = tool_catalog.MCP_VERSION
CATALOG_VERSION = tool_catalog.MCP_VERSION

AUTH_SCOPES_AVAILABLE = [
    "ralfia:read", "ralfia:write", "ralfia:agents", "ralfia:admin",
    "ralfia:memory:read", "ralfia:memory:write", "ralfia:memory:finalize",
    "ralfia:private_memory",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_payload() -> dict[str, Any]:
    tool_names = _tool_names()
    tools = []
    for name in tool_names:
        details = tool_catalog.describe_tool(name)
        if details.get("ok"):
            tools.append(details)
    payload = {
        "server_version": SERVER_VERSION,
        "bridge_version": BRIDGE_VERSION,
        "catalog_version": CATALOG_VERSION,
        "tools": tools,
        "resource": "resource://RalfIA_MCP",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return {**payload, "manifest_hash": digest, "tool_count": len(tools)}


def _tool_names() -> list[str]:
    return sorted(tool_catalog.ALL_MCP_TOOL_NAMES)


def _tool_names_hash(tool_names: list[str]) -> str:
    raw = json.dumps(tool_names, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _catalog_snapshot() -> dict[str, Any]:
    tool_names = _tool_names()
    manifest = _manifest_payload()
    return {
        "server_version": SERVER_VERSION,
        "bridge_version": BRIDGE_VERSION,
        "catalog_version": CATALOG_VERSION,
        "tool_names": tool_names,
        "tool_names_hash": _tool_names_hash(tool_names),
        "tool_count": manifest["tool_count"],
        "manifest_hash": manifest["manifest_hash"],
    }


def _stored_runtime_snapshot() -> dict[str, Any]:
    state = mongo_store.get_coordination_state("documentary_sync")
    if not state.get("ok"):
        return {}
    runtime = (state.get("state") or {}).get("mcp_runtime") or {}
    if isinstance(runtime, dict):
        return runtime
    return {}


def _catalog_guard(previous_runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    current = _catalog_snapshot()
    prev_runtime = previous_runtime if previous_runtime is not None else _stored_runtime_snapshot()
    prev_tools = sorted(prev_runtime.get("tool_names") or [])
    removed = sorted(set(prev_tools) - set(current["tool_names"]))
    added = sorted(set(current["tool_names"]) - set(prev_tools))
    if removed:
        status = "tool_loss_detected"
    elif added:
        status = "catalog_expanded"
    elif prev_tools:
        status = "catalog_stable"
    else:
        status = "no_baseline"
    return {
        "status": status,
        "tool_loss_detected": bool(removed),
        "removed_tools": removed,
        "added_tools": added,
        "current_tool_count": current["tool_count"],
        "previous_tool_count": len(prev_tools),
        "current_tool_names_hash": current["tool_names_hash"],
        "previous_tool_names_hash": prev_runtime.get("tool_names_hash"),
        "baseline_key": "documentary_sync",
    }


def _visibility(required_scopes: list[str]) -> str:
    protected = {"ralfia:write", "ralfia:admin", "ralfia:agents", "ralfia:publish"}
    if any(scope in protected for scope in required_scopes):
        return "protected"
    return "read_only"


def mcp_version(session_id: str | None = None) -> dict[str, Any]:
    manifest = _manifest_payload()
    guard = _catalog_guard()
    auth_status = "api_key+oauth" if MCP_API_KEY else "oauth_only"
    oauth_scopes = AUTH_SCOPES_AVAILABLE
    runtime_tool_count = len(tool_catalog.ALL_MCP_TOOL_NAMES)
    return {
        "ok": True,
        "timestamp": _now_iso(),
        "server_version": SERVER_VERSION,
        "bridge_version": BRIDGE_VERSION,
        "manifest_version": manifest["manifest_hash"][:12],
        "catalog_version": CATALOG_VERSION,
        "catalog_tool_count": manifest["tool_count"],
        "runtime_tool_count": runtime_tool_count,
        "manifest_hash": manifest["manifest_hash"],
        "tool_names": _tool_names(),
        "tool_names_hash": _tool_names_hash(_tool_names()),
        "tool_name_count": runtime_tool_count,
        "catalog_guard": guard,
        "auth_status": auth_status,
        "oauth_scopes": oauth_scopes,
        "session_id": session_id,
        "public_url": f"{MCP_PUBLIC_URL.rstrip('/')}/mcp",
        "oauth_issuer": OAUTH_ISSUER,
        "updated_at": ralfia_time.now_utc_iso(),
    }


def list_mcp_capabilities() -> dict[str, Any]:
    manifest = _manifest_payload()
    resources = ["resource://RalfIA_MCP"]
    schemas: dict[str, Any] = {}
    tools: list[dict[str, Any]] = []
    for name in sorted(tool_catalog.ALL_MCP_TOOL_NAMES):
        details = tool_catalog.describe_tool(name)
        if not details.get("ok"):
            continue
        tool_item = {
            "name": details["name"],
            "description": details["description"],
            "required_scopes": details["required_scopes"],
            "visibility": _visibility(details["required_scopes"]),
            "risk_level": details["risk_level"],
            "reads_from": details["reads_from"],
            "writes_to": details["writes_to"],
            "example_payload": details["example_payload"],
        }
        tools.append(tool_item)
        schemas[name] = {
            "input_schema": details["input_schema"],
            "output_schema": details["output_schema"],
        }
    return {
        "ok": True,
        "version": manifest["catalog_version"],
        "updated_at": ralfia_time.now_utc_iso(),
        "catalog_tool_count": manifest["tool_count"],
        "runtime_tool_count": len(tool_catalog.ALL_MCP_TOOL_NAMES),
        "manifest_hash": manifest["manifest_hash"],
        "resources": resources,
        "schemas": schemas,
        "required_scopes": AUTH_SCOPES_AVAILABLE,
        "visibility": {
            tool["name"]: tool["visibility"] for tool in tools
        },
        "tools": tools,
    }


def describe_tool(tool_name: str) -> dict[str, Any]:
    details = tool_catalog.describe_tool(tool_name)
    if not details.get("ok"):
        return details
    return {
        "ok": True,
        "name": details["name"],
        "description": details["description"],
        "input_schema": details["input_schema"],
        "output_schema": details["output_schema"],
        "required_scopes": details["required_scopes"],
        "example_payload": details["example_payload"],
        "example_response": {},
        "risk_level": details["risk_level"],
        "reads_from": details["reads_from"],
        "writes_to": details["writes_to"],
        "visibility": _visibility(details["required_scopes"]),
        "version": details["version"],
    }


def system_debug() -> dict[str, Any]:
    health = mongo_store.ping_mongo()
    error_log = mongo_store.get_mcp_error_log(limit=20)
    auth_failures = mongo_store.get_mcp_error_log(limit=20, error_type="unauthorized")
    missing_scopes = mongo_store.get_mcp_error_log(limit=20, error_type="missing_scope")
    validation_errors = mongo_store.get_mcp_error_log(
        limit=20,
        error_type="schema_validation_error",
    )
    manifest = _manifest_payload()
    guard = _catalog_guard()
    return {
        "ok": True,
        "timestamp": _now_iso(),
        "mcp_health": {
            "ok": bool(health.get("ok")),
            "public_url": f"{MCP_PUBLIC_URL.rstrip('/')}/mcp",
            "internal_url": f"http://127.0.0.1:8102/mcp",
            "catalog_tool_count": manifest["tool_count"],
            "runtime_tool_count": len(tool_catalog.ALL_MCP_TOOL_NAMES),
            "catalog_version": CATALOG_VERSION,
            "manifest_hash": manifest["manifest_hash"],
            "tool_names_hash": _tool_names_hash(_tool_names()),
            "sse_stream_status": "streamable_http",
            "oauth_enabled": bool(OAUTH_ISSUER),
        },
        "oauth_health": {
            "issuer": OAUTH_ISSUER,
            "auth_status": "enabled" if OAUTH_ISSUER else "disabled",
            "api_key_fallback": bool(MCP_API_KEY),
        },
        "gateway_health": {
            "public_url": f"{MCP_PUBLIC_URL.rstrip('/')}/mcp",
            "upstream_internal_url": f"http://127.0.0.1:8102/mcp",
            "cache_risk": "high_for_chat_clients_if_connector_not_refreshed",
        },
        "catalog_guard": guard,
        "errors": error_log,
        "auth_failures": auth_failures,
        "missing_scopes": missing_scopes,
        "validation_errors": validation_errors,
        "current_catalog_shape": f"{manifest['tool_count']} tools",
    }


def diagnose_mcp_session(
    client_tool_count: int | None = None,
    client_catalog_version: str | None = None,
    client_seen_tools: list[str] | None = None,
    session_id: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    manifest = _manifest_payload()
    current_guard = _catalog_guard()
    expected_tools = sorted(tool_catalog.ALL_MCP_TOOL_NAMES)
    seen_tools = sorted(set(client_seen_tools or []))
    stale_catalog = False
    reasons: list[str] = []

    if client_catalog_version and client_catalog_version != CATALOG_VERSION:
        stale_catalog = True
        reasons.append("client_catalog_version_mismatch")
    if client_tool_count is not None and client_tool_count < manifest["tool_count"]:
        stale_catalog = True
        reasons.append("client_tool_count_older_than_server")
    if seen_tools and any(tool not in expected_tools for tool in seen_tools):
        reasons.append("client_reports_unknown_tools")
    if client_tool_count is None and client_catalog_version is None and not seen_tools:
        reasons.append("client_context_not_provided")

    likely_issue = (
        "stale_catalog"
        if stale_catalog
        else "oauth_refresh_needed"
        if not MCP_API_KEY and not OAUTH_ISSUER
        else "stream_or_connector_cache"
    )
    recommended_actions = [
        "refresh connector",
        "reopen chat in a new conversation",
        "re-authorize OAuth if the chat is holding an old token",
        "reload the connector manifest after catalog_version changes",
    ]
    if stale_catalog:
        recommended_actions.insert(0, "recreate or refresh the connector entry")
    return {
        "ok": True,
        "timestamp": _now_iso(),
        "session_id": session_id,
        "user_agent": user_agent,
        "this_client_sees_tools": client_tool_count,
        "this_client_catalog_version": client_catalog_version,
        "client_seen_tools": seen_tools,
        "expected_tool_count": manifest["tool_count"],
        "expected_catalog_version": CATALOG_VERSION,
        "expected_tools": expected_tools,
        "expected_tool_names_hash": _tool_names_hash(expected_tools),
        "catalog_guard": current_guard,
        "stale_catalog": stale_catalog,
        "likely_issue": likely_issue,
        "reasons": reasons,
        "needs_reauthorize_oauth": stale_catalog,
        "needs_refresh_connector": stale_catalog or bool(reasons),
        "recommended_actions": recommended_actions,
        "server_snapshot": {
            "server_version": SERVER_VERSION,
            "bridge_version": BRIDGE_VERSION,
            "manifest_hash": manifest["manifest_hash"],
            "public_url": f"{MCP_PUBLIC_URL.rstrip('/')}/mcp",
        },
    }
