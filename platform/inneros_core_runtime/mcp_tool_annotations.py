"""MCP tool annotations — classification and hints for client approval UX."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Literal

ToolClass = Literal["read", "additive_write", "destructive", "unknown"]

CATALOG_VERSION_BUMP_HINT = "2.72.0"

READ_PURE: frozenset[str] = frozenset(
    {
        "mcp_version",
        "diagnose_mcp_session",
        "get_coordination_live",
        "get_coordination_liveness_summary",
        "list_ops_tasks",
        "dev_swarm_scheduler_status",
        "dev_swarm_scope_status",
        "device_fabric_inventory",
        "device_fabric_health",
        "device_fabric_get",
        "device_fabric_providers",
        "device_fabric_discover",
        "device_fabric_capabilities",
        "bellini_guardian_status",
        "bellini_guardian_dashboard",
        "a2a_status",
        "a2a_agent_cards",
        "bootstrap_context",
        "list_agent_messages",
        "list_mcp_tool_profiles",
        "route_mcp_tools",
        "get_operational_runbooks",
        "get_quote_tracking",
        "record_site_network_snapshot",
        "list_site_network_snapshots",
        "capability_search",
        "capability_describe",
        "capability_execution",
        "project_runtime_bootstrap",
        "cursor_list_claimable_ops_tasks",
        "codex_list_claimable_ops_tasks",
        "antigravity_list_claimable_ops_tasks",
        "gemini_list_claimable_ops_tasks",
        "resource_fabric_status",
        "durable_coordination_spine_status",
        "durable_coordination_temporal_status",
        "a2a_task_status",
        "accounting_summary",
        "grandstream_gwn_api_capabilities",
        "grandstream_gwn_full_snapshot",
        "ruijie_reyee_api_capabilities",
        "ruijie_reyee_full_snapshot",
        "build_client_360_snapshot",
        "cognitive_kernel_check",
        "classify_knowledge_seed",
        "classify_task_runtime",
        "agent_iskcon_capabilities",
        "peer_ops_logs",
        "peer_ops_snapshot",
        "peer_observability_snapshot",
        "peer_net_interfaces",
        "peer_wifi_scan",
        "peer_route_check",
        "peer_hardware_discovery",
        "peer_python_runtime",
        "peer_node_capability_matrix",
        "peer_host_ops_policy",
        "run_failover_dry_run",
        "cloud_deploy_dry_run",
        "gcp_list_projects",
        "brightdata_mcp_list_tools",
    }
)

ADDITIVE_WRITE: frozenset[str] = frozenset(
    {
        "create_agent_message",
        "ack_agent_message",
        "ack_coordination_revision",
        "save_conversation_batch",
        "update_memory",
        "finalize_conversation",
        "create_quote_draft",
        "update_quote_draft",
        "generate_quote_intro",
        "generate_quote_pdf",
        "render_quote_document",
        "send_quote_delivery",
        "resolve_party",
        "resolve_client",
        "resolve_agent",
        "sync_quote_sources",
        "capability_invoke",
        "add_notion_page_comment",
        "capture_backlog_item",
        "agent_daily_save_note",
        "add_observation",
        "attach_media_to_asset",
        "attach_media_to_visit",
        "bootstrap_notion_coordination_db",
        "bootstrap_notion_schema",
        "agent_health_save",
        "agent_funding_register_from_email",
        "agent_invoice_prepare",
        "agent_quote_prepare",
        "agent_report_technical",
        "generate_agent_activity_report",
        "finalize_session_handoff",
        "project_runtime_register",
        "project_runtime_resolve",
        "sync_platform_to_intel",
        "cloud_deploy_plan",
        "gcp_auth_begin",
        "gcp_auth_submit_code",
        "cloud_authorization_request",
        "cloud_approval_issue",
        "cloud_apply_window_set",
        "gcp_auth_bootstrap",
        "coordination_backlog_hygiene",
        "reconcile_runtime_state",
        "project_runtime_reconcile",
        "project_runtime_migrate_existing",
        "log_coordination_event",
        "save_chatgpt_note",
    }
)

DESTRUCTIVE_EXPLICIT: frozenset[str] = frozenset(
    {
        "dev_swarm_launch_task",
        "dev_swarm_scheduler_start",
        "dev_swarm_scheduler_stop",
        "dev_swarm_scheduler_tick",
        "cursor_owner_order",
        "cursor_claim_ops_task",
        "cursor_complete_ops_task",
        "cursor_authorize_ops_task",
        "codex_owner_order",
        "codex_claim_ops_task",
        "codex_complete_ops_task",
        "antigravity_owner_order",
        "antigravity_claim_ops_task",
        "antigravity_complete_ops_task",
        "gemini_owner_order",
        "gemini_claim_ops_task",
        "gemini_complete_ops_task",
        "bellini_governed_action",
        "send_whatsapp_document",
        "broadcast_whatsapp_message",
        "broadcast_whatsapp_groups",
        "grandstream_gwn_device_reboot",
        "grandstream_gwn_ssid_update",
        "grandstream_gwn_network_ops",
        "ruijie_reyee_network_ops",
        "a2a_dispatch",
        "approve_and_develop_project",
        "approve_pipeline_draft",
        "resource_fabric_bootstrap",
        "durable_coordination_publish_event",
        "delete_memory",
        "purge_memory",
        "device_fabric_bind",
        "device_fabric_probe",
        "dispatch_local_agent",
        "invoke_agent",
        "ralfia_dispatch",
        "route_agent_request",
        "vero_dispatch",
        "agent_iskcon_dispatch",
        "cloud_deploy_apply",
        "clone_tenant_deployment",
        "dmx_set_scene",
        "dmx_blackout",
        "peer_ops_action",
        "peer_wifi_connect",
        "peer_wifi_disconnect",
        "peer_secret_store_wifi",
        "peer_wifi_forget",
        "peer_package_install",
        "peer_package_remove",
        "peer_user_service",
        "peer_project_fs",
        "run_service_guardian",
        "run_health_watch",
        "run_daily_companion",
        "agent_funding_scan_emails",
        "agent_hackathon_scan_emails",
    }
)

READ_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "describe_",
    "diagnose_",
    "fetch_",
    "read_",
    "poll_",
    "watch_",
    "inspect_",
    "preview_",
    "explain_",
    "lookup_",
    "query_",
)
ADDITIVE_PREFIXES = (
    "create_",
    "save_",
    "update_",
    "ack_",
    "register_",
    "append_",
    "enqueue_",
    "add_",
    "attach_",
    "generate_",
    "render_",
    "sync_",
    "resolve_",
    "bootstrap_",
    "finalize_",
    "log_",
    "notify_",
    "publish_",
    "ingest_",
    "index_",
    "translate_",
    "draft_",
    "prepare_",
    "upsert_",
    "merge_",
    "link_",
    "set_",
    "put_",
    "post_",
    "send_",
    "write_",
)
DESTRUCTIVE_PREFIXES = (
    "dev_swarm_launch_",
    "delete_",
    "remove_",
    "purge_",
    "reboot_",
    "claim_",
    "pay_",
    "send_whatsapp_",
    "broadcast_",
    "deploy_",
    "apply_",
    "destroy_",
    "drop_",
    "terminate_",
    "kill_",
    "wipe_",
    "revoke_",
    "cancel_",
    "abort_",
    "force_",
    "uninstall_",
    "blackout_",
    "dispatch_",
    "invoke_",
    "launch_",
    "execute_",
    "run_",
    "migrate_",
    "reconcile_",
    "approve_",
    "authorize_",
    "complete_",
    "install_",
    "unbind_",
    "format_",
)

READ_SUFFIXES = (
    "_status",
    "_summary",
    "_health",
    "_inventory",
    "_catalog",
    "_capabilities",
    "_snapshot",
    "_check",
    "_timeline",
    "_metrics",
    "_report_readonly",
    "_dry_run",
    "_preview",
)

DESTRUCTIVE_INFIX = (
    "_network_ops",
    "_device_reboot",
    "_ssid_update",
    "_governed_action",
    "_owner_order",
    "_package_install",
    "_package_remove",
    "_wifi_connect",
    "_wifi_disconnect",
    "_deploy_apply",
)


@lru_cache(maxsize=1)
def _tool_scopes() -> dict[str, str]:
    try:
        from raphiia_openai.auth_middleware import TOOL_SCOPES
    except Exception:
        return {}
    out: dict[str, str] = {}
    for key, val in TOOL_SCOPES.items():
        if isinstance(val, str):
            out[key] = val
        elif isinstance(val, (list, tuple, set)):
            out[key] = " ".join(str(v) for v in val)
    return out


def _classify_by_scope(name: str) -> ToolClass | None:
    scope = _tool_scopes().get(name, "")
    scopes = set(scope.split()) if scope else set()
    if not scopes:
        return None
    if scopes <= {"ralfia:read"} or scopes == {"ralfia:read"}:
        return "read"
    if "ralfia:admin" in scopes:
        return "destructive"
    if "ralfia:agents" in scopes:
        lower = name.lower()
        if any(x in lower for x in ("launch", "deploy", "delete", "approve", "claim", "order", "dispatch", "invoke")):
            return "destructive"
        return "additive_write"
    if "ralfia:write" in scopes or "ralfia:memory:write" in scopes:
        return "additive_write"
    if "ralfia:read" in scopes:
        return "read"
    return None


def classify_tool(name: str) -> ToolClass:
    n = (name or "").strip()
    if not n:
        return "unknown"
    lower = n.lower()
    if n in READ_PURE:
        return "read"
    if n in DESTRUCTIVE_EXPLICIT:
        return "destructive"
    if n == "poll_agent_inbox":
        return "read"
    if n in ADDITIVE_WRITE:
        return "additive_write"
    scoped = _classify_by_scope(n)
    if scoped:
        return scoped
    for frag in DESTRUCTIVE_INFIX:
        if frag in lower:
            return "destructive"
    for prefix in DESTRUCTIVE_PREFIXES:
        if lower.startswith(prefix):
            if lower.endswith("_dry_run") or "dry_run" in lower:
                return "read"
            if lower.startswith("run_") and any(x in lower for x in ("watch", "scan", "companion", "guardian")):
                return "destructive"
            return "destructive"
    for prefix in ADDITIVE_PREFIXES:
        if lower.startswith(prefix):
            return "additive_write"
    for prefix in READ_PREFIXES:
        if lower.startswith(prefix):
            return "read"
    for suffix in READ_SUFFIXES:
        if lower.endswith(suffix):
            return "read"
    if lower.endswith("_status") or lower.endswith("_summary") or lower.endswith("_health"):
        return "read"
    if "agent_" in lower and any(x in lower for x in ("scan_", "status", "summary", "capabilities")):
        return "read"
    if lower.startswith("agent_") and any(x in lower for x in ("prepare", "save", "register", "report")):
        return "additive_write"
    if lower.startswith("git_") and "push" in lower:
        return "destructive"
    if lower.startswith("git_"):
        return "read"
    if lower.startswith("docker_") and any(x in lower for x in ("run", "exec", "rm", "kill", "prune")):
        return "destructive"
    if lower.startswith("docker_"):
        return "read"
    if lower.startswith("fs_") and any(x in lower for x in ("write", "delete", "move", "patch")):
        return "destructive"
    if lower.startswith("fs_"):
        return "read"
    if lower.startswith("terminal_") or lower.startswith("shell_"):
        return "destructive"
    # Safe default for full catalog: prefer additive over false-destructive reads
    if lower.startswith(("get_", "list_", "fetch_", "search_")):
        return "read"
    return "additive_write"


def annotations_for_tool(name: str, *, tool_class: ToolClass | None = None) -> dict[str, bool]:
    tc = tool_class or classify_tool(name)
    if tc == "read":
        return {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
    if tc == "additive_write":
        return {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
    if tc == "destructive":
        return {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True}
    return {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True}


def poll_agent_inbox_annotations(arguments: dict[str, Any] | None) -> dict[str, bool]:
    auto_ack = bool((arguments or {}).get("auto_ack"))
    if auto_ack:
        return annotations_for_tool("ack_agent_message")
    return annotations_for_tool("poll_agent_inbox", tool_class="read")
