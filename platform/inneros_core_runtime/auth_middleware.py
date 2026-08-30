"""MCP auth middleware: internal API key plus OAuth Bearer scopes."""

from __future__ import annotations

import time
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers, get_http_request
from fastmcp.server.middleware import Middleware, MiddlewareContext

from raphiia_openai import mongo_store
from raphiia_openai.oauth_store import validate_access_token
from raphiia_openai.settings import OAUTH_MCP_RESOURCE

# Cache credenciales por sesión MCP (streamable-http no siempre reenvía headers en tools/call).
_SESSION_AUTH: dict[str, dict[str, str]] = {}
_SESSION_AUTH_TS: dict[str, float] = {}
_SESSION_AUTH_TTL_SEC = 24 * 3600
_SESSION_AUTH_MAX = 500

TOOL_SCOPES = {
    "search": "ralfia:read",
    "fetch": "ralfia:read",
    "get_context_summary": "ralfia:read",
    "list_pipeline": "ralfia:read",
    "get_coordination_summary": "ralfia:read",
    "health_check": "ralfia:read",
    "system_health": "ralfia:read",
    "get_mcp_fleet_status": "ralfia:read",
    "get_unified_stack_status": "ralfia:read",
    "reconcile_runtime_state": "ralfia:read",
    "run_health_watch": "ralfia:read",
    "list_ralphia_agents": "ralfia:read",
    "list_peer_ops_services": "ralfia:read",
    "peer_ops_snapshot": "ralfia:read",
    "peer_ops_status": "ralfia:read",
    "peer_ops_logs": "ralfia:read",
    "peer_ops_action": "ralfia:write",
    "peer_net_interfaces": "ralfia:read",
    "peer_wifi_scan": "ralfia:read",
    "peer_wifi_status": "ralfia:read",
    "peer_route_check": "ralfia:read",
    "peer_wifi_connect": "ralfia:agents",
    "peer_wifi_disconnect": "ralfia:agents",
    "peer_secret_store_wifi": "ralfia:agents",
    "peer_wifi_forget": "ralfia:agents",
    "peer_package_status": "ralfia:read",
    "peer_package_install": "ralfia:agents",
    "peer_package_remove": "ralfia:agents",
    "peer_hardware_discovery": "ralfia:read",
    "peer_python_runtime": "ralfia:agents",
    "peer_user_service": "ralfia:agents",
    "peer_node_capability_matrix": "ralfia:read",
    "peer_host_ops_policy": "ralfia:read",
    "peer_observability_snapshot": "ralfia:read",
    "peer_project_fs": "ralfia:agents",
    "project_runtime_register": "ralfia:agents",
    "project_runtime_resolve": "ralfia:read",
    "project_runtime_status": "ralfia:read",
    "project_runtime_bootstrap": "ralfia:agents",
    "project_runtime_reconcile": "ralfia:agents",
    "project_runtime_migrate_existing": "ralfia:agents",
    "sync_platform_to_intel": "ralfia:write",
    "run_failover_dry_run": "ralfia:read",
    "clone_tenant_deployment": "ralfia:write",
    "cloud_deploy_status": "ralfia:read",
    "cloud_deploy_plan": "ralfia:read",
    "cloud_provider_status": "ralfia:read",
    "cloud_deploy_dry_run": "ralfia:read",
    "cloud_deploy_apply": "ralfia:agents",
    "gcp_auth_bootstrap": "ralfia:read",
    "gcp_auth_begin": "ralfia:agents",
    "gcp_auth_submit_code": "ralfia:agents",
    "gcp_auth_status": "ralfia:read",
    "cloud_authorization_request": "ralfia:agents",
    "cloud_authorization_status": "ralfia:read",
    "cloud_approval_issue": "ralfia:agents",
    "cloud_approval_status": "ralfia:read",
    "cloud_apply_window_set": "ralfia:agents",
    "cloud_apply_window_status": "ralfia:read",
    "gcp_list_projects": "ralfia:read",
    "gcp_billing_accounts_list": "ralfia:read",
    "gcp_list_billing_accounts": "ralfia:read",
    "gcp_billing_projects_list": "ralfia:read",
    "gcp_project_billing_info": "ralfia:read",
    "gcp_get_project_billing": "ralfia:read",
    "gcp_billing_credits_status": "ralfia:read",
    "gcp_allowlist_project": "ralfia:agents",
    "gcp_allowlist_billing_account": "ralfia:agents",
    "gcp_budgets_list": "ralfia:read",
    "gcp_budget_list": "ralfia:read",
    "gcp_budget_status": "ralfia:read",
    "gcp_budget_create": "ralfia:agents",
    "gcp_costs_query": "ralfia:read",
    "gcp_billing_cost_summary": "ralfia:read",
    "gcp_billing_export_status": "ralfia:read",
    "gcp_billing_export_prepare": "ralfia:agents",
    "gcp_quotas_list": "ralfia:read",
    "gcp_project_iam_policy": "ralfia:read",
    "gcp_project_iam_add_binding": "ralfia:agents",
    "gcp_artifact_registry_list": "ralfia:read",
    "gcp_artifact_registry_create": "ralfia:agents",
    "gcp_project_setup_preflight": "ralfia:read",
    "gcp_cloud_run_status": "ralfia:read",
    "gcp_cloud_run_revisions": "ralfia:read",
    "gcp_cloud_run_traffic": "ralfia:read",
    "gcp_logs_query": "ralfia:read",
    "gcp_secret_manager_metadata": "ralfia:read",
    "gcp_firestore_status": "ralfia:read",
    "gcp_pubsub_list": "ralfia:read",
    "gcp_gemini_or_vertex_status": "ralfia:read",
    "gcp_service_health_check": "ralfia:read",
    "provider_manifest_schema": "ralfia:read",
    "provider_list_manifests": "ralfia:read",
    "provider_preflight": "ralfia:read",
    "resource_fabric_status": "ralfia:read",
    "resource_fabric_route": "ralfia:read",
    "resource_fabric_bootstrap": "ralfia:agents",
    "resource_fabric_link_project_capability": "ralfia:agents",
    "local_gitlab_status": "ralfia:read",
    "local_gitlab_store_pat_server_side": "ralfia:agents",
    "local_gitlab_glab_preflight": "ralfia:read",
    "local_gitlab_list_projects": "ralfia:read",
    "local_gitlab_list_groups": "ralfia:read",
    "local_gitlab_user_profile": "ralfia:read",
    "local_gitlab_user_events": "ralfia:read",
    "local_gitlab_discover_contribution_issues": "ralfia:read",
    "local_gitlab_project_summary": "ralfia:read",
    "local_gitlab_list_merge_requests": "ralfia:read",
    "local_gitlab_create_draft_merge_request": "ralfia:agents",
    "local_gitlab_list_issues": "ralfia:read",
    "local_gitlab_list_pipelines": "ralfia:read",
    "local_gitlab_resource_sync": "ralfia:agents",
    "local_gitlab_prepare_github_mirrors": "ralfia:agents",
    "local_gitlab_credit_status": "ralfia:read",
    "ide_task_bridge_status": "ralfia:read",
    "ide_dispatch_task": "ralfia:agents",
    "ide_task_status": "ralfia:read",
    "ide_claim_task": "ralfia:agents",
    "ide_mark_task_running": "ralfia:agents",
    "ide_complete_task": "ralfia:agents",
    "dev_swarm_watchdog_record_anomaly": "ralfia:agents",
    "dev_swarm_watchdog_close_anomaly": "ralfia:agents",
    "dev_swarm_watchdog_summary": "ralfia:read",
    "dev_swarm_watchdog_demo_closed_loop": "ralfia:agents",
    "dev_swarm_watchdog_dedupe_ops": "ralfia:agents",
    "local_discord_configure_public_app": "ralfia:agents",
    "local_discord_status": "ralfia:read",
    "local_discord_interaction_gateway_status": "ralfia:read",
    "local_discord_set_interactions_endpoint_url": "ralfia:agents",
    "local_discord_store_bot_token_server_side": "ralfia:agents",
    "local_discord_store_webhook_url_server_side": "ralfia:agents",
    "local_discord_oauth_install_url": "ralfia:read",
    "local_discord_list_guilds": "ralfia:read",
    "local_discord_list_channels": "ralfia:read",
    "local_discord_create_text_channel": "ralfia:agents",
    "local_discord_list_channel_webhooks": "ralfia:read",
    "local_discord_create_channel_webhook": "ralfia:agents",
    "local_discord_create_thread": "ralfia:agents",
    "local_discord_list_channel_messages": "ralfia:read",
    "local_discord_resolve_channel": "ralfia:read",
    "local_discord_search_channel_messages": "ralfia:read",
    "local_discord_read_configured_channels": "ralfia:read",
    "local_discord_search_configured_channels": "ralfia:read",
    "local_discord_send_channel_message": "ralfia:agents",
    "local_discord_send_named_channel_message": "ralfia:agents",
    "local_discord_send_webhook_message": "ralfia:agents",
    "local_discord_list_guild_commands": "ralfia:read",
    "local_discord_register_guild_commands": "ralfia:agents",
    "local_discord_add_reaction": "ralfia:agents",
    "local_discord_resource_sync": "ralfia:agents",
    "tenant_reconciliation_report": "ralfia:read",
    "digitalocean_status": "ralfia:read",
    "digitalocean_preflight": "ralfia:read",
    "digitalocean_balance": "ralfia:read",
    "digitalocean_store_pat_server_side": "ralfia:agents",
    "digitalocean_list_regions": "ralfia:read",
    "digitalocean_list_sizes": "ralfia:read",
    "digitalocean_list_images": "ralfia:read",
    "digitalocean_list_ssh_keys": "ralfia:read",
    "digitalocean_create_ssh_key": "ralfia:agents",
    "digitalocean_register_server_public_ssh_key": "ralfia:agents",
    "digitalocean_list_droplets": "ralfia:read",
    "digitalocean_create_gpu_droplet": "ralfia:agents",
    "digitalocean_get_droplet": "ralfia:read",
    "digitalocean_destroy_droplet": "ralfia:agents",
    "digitalocean_cost_session_status": "ralfia:read",
    "digitalocean_cleanup_failed_sessions": "ralfia:agents",
    "brightdata_status": "ralfia:read",
    "brightdata_balance": "ralfia:read",
    "brightdata_store_api_token_server_side": "ralfia:agents",
    "brightdata_mcp_list_tools": "ralfia:read",
    "brightdata_mcp_call_tool": "ralfia:agents",
    "brightdata_search_engine": "ralfia:agents",
    "brightdata_scrape_as_markdown": "ralfia:agents",
    "gcp_create_project": "ralfia:agents",
    "gcp_link_billing": "ralfia:agents",
    "gcp_enable_apis": "ralfia:agents",
    "gcp_build_image": "ralfia:agents",
    "gcp_cloud_run_deploy": "ralfia:agents",
    "gcp_cloud_run_rollback": "ralfia:agents",
    "gcp_secret_manager_create_version": "ralfia:agents",
    "gcp_firestore_create_db": "ralfia:agents",
    "gcp_pubsub_create_topic": "ralfia:agents",
    "gcp_pubsub_create_subscription": "ralfia:agents",
    "provider_register_manifest": "ralfia:agents",
    "cloudflare_status": "ralfia:read",
    "cloudflare_dns_upsert": "ralfia:write",
    "cloudflare_dns_delete": "ralfia:write",
    "cloudflare_waf_skip_challenge": "ralfia:write",
    "cloudflare_waf_delete_hostname_rules": "ralfia:write",
    "cloudflare_tunnel_ingress_status": "ralfia:read",
    "cloudflare_hostname_health_check": "ralfia:read",
    "cloudflare_prepare_hostname": "ralfia:write",
    "get_development_roadmap": "ralfia:read",
    "list_local_agents": "ralfia:read",
    "get_agent_catalog": "ralfia:read",
    "resolve_agent": "ralfia:read",
    "invoke_agent": "ralfia:agents",
    "ralfia_dispatch": "ralfia:agents",
    "ralfia_status": "ralfia:read",
    "dispatch_local_agent": "ralfia:agents",
    "run_self_heal_cycle": "ralfia:write",
    "run_service_guardian": "ralfia:read",
    "agent_quote_prepare": "ralfia:agents",
    "agent_report_technical": "ralfia:agents",
    "agent_invoice_prepare": "ralfia:agents",
    "run_daily_companion": "ralfia:read",
    "agent_daily_save_note": ["ralfia:memory:write", "ralfia:private_memory"],
    "agent_health_save": ["ralfia:memory:write", "ralfia:private_memory"],
    "agent_health_timeline": ["ralfia:memory:read", "ralfia:private_memory"],
    "agent_health_summary": ["ralfia:memory:read", "ralfia:private_memory"],
    "agent_iskcon_status": "ralfia:read",
    "agent_iskcon_capabilities": "ralfia:read",
    "agent_iskcon_domain": "ralfia:read",
    "agent_iskcon_ffl_log": "ralfia:write",
    "agent_iskcon_ffl_timeline": "ralfia:read",
    "agent_iskcon_contacts_summary": "ralfia:read",
    "agent_iskcon_dispatch": "ralfia:write",
    "judge_workflow_start": "ralfia:agents",
    "judge_workflow_continue": "ralfia:agents",
    "judge_workflow_execute": "ralfia:agents",
    "judge_workflow_get": "ralfia:read",
    "judge_workflow_list": "ralfia:read",
    "judge_trace_record": "ralfia:agents",
    "judge_trace_current": "ralfia:read",
    "judge_trace_history": "ralfia:read",
    "judge_trace_detail": "ralfia:read",
    "judge_trace_kpis": "ralfia:read",
    "judge_resource_telemetry": "ralfia:read",
    "judge_safe_trigger": "ralfia:agents",
    "judge_console_content_get": "ralfia:read",
    "judge_model_routing_policy": "ralfia:read",
    "judge_mi325x_deploy": "ralfia:agents",
    "agent_iskcon_sources": "ralfia:read",
    "agent_iskcon_yoga_campaign": "ralfia:write",
    "agent_iskcon_class_update": "ralfia:write",
    "agent_hackathon_status": "ralfia:read",
    "agent_hackathon_scan_emails": "ralfia:read",
    "agent_funding_status": "ralfia:read",
    "agent_funding_scan_emails": "ralfia:read",
    "agent_funding_register_from_email": "ralfia:write",
    "get_project_map": "ralfia:read",
    "list_coordination_files": "ralfia:read",
    "list_coordination_docs": "ralfia:read",
    "read_coordination_file": "ralfia:read",
    "read_coordination_doc": "ralfia:read",
    "search_coordination_docs": "ralfia:read",
    "get_chatgpt_workspace": "ralfia:read",
    "bootstrap_context": "ralfia:read",
    "get_operational_runbooks": "ralfia:read",
    "get_coordination_live": "ralfia:read",
    "inneros_agent_fabric_status": "ralfia:read",
    "ack_coordination_revision": "ralfia:write",
    "create_ops_task": "ralfia:write",
    "complete_ops_task": "ralfia:write",
    "codex_continuity_checkpoint": "ralfia:write",
    "list_ops_tasks": "ralfia:read",
    "get_agent_mailboxes": "ralfia:read",
    "identify_agent_session": "ralfia:agents",
    "ack_agent_message": "ralfia:agents",
    "poll_agent_inbox": "ralfia:agents",
    "update_ops_task_state": "ralfia:agents",
    "heartbeat_ops_task": "ralfia:agents",
    "manage_coordination_lock": "ralfia:agents",
    "migrate_racb_records": "ralfia:admin",
    "import_google_contacts_csv": "ralfia:write",
    "list_contacts": "ralfia:read",
    "resolve_contact": "ralfia:read",
    "link_contact_entities": "ralfia:write",
    "create_whatsapp_reminder": "ralfia:write",
    "list_whatsapp_reminders": "ralfia:read",
    "process_whatsapp_inbound_event": "ralfia:write",
    "run_due_whatsapp_reminders": "ralfia:write",
    "broadcast_whatsapp_message": "ralfia:write",
    "broadcast_whatsapp_groups": "ralfia:write",
    "get_whatsapp_status": "ralfia:read",
    "get_server_status": "ralfia:read",
    "get_infrastructure_status": "ralfia:read",
    "get_whatsapp_commands_help": "ralfia:read",
    "trigger_email_poll": "ralfia:write",
    "ha_ping": "ralfia:read",
    "ha_list_entities": "ralfia:read",
    "ha_get_entity": "ralfia:read",
    "ha_list_devices": "ralfia:read",
    "ha_list_entity_registry": "ralfia:read",
    "ha_call_service": "ralfia:write",
    "ha_rename_device": "ralfia:write",
    "ha_rename_entity_name": "ralfia:write",
    "ha_search_entity_references": "ralfia:read",
    "ha_batch_rename": "ralfia:write",
    "ha_turn_on_light": "ralfia:write",
    "ha_turn_off_light": "ralfia:write",
    "run_home_ops_cycle": "ralfia:write",
    "list_monitored_emails": "ralfia:read",
    "sync_email_archive": "ralfia:write",
    "save_productivity_event": "ralfia:write",
    "list_productivity_events": "ralfia:read",
    "summarize_productivity_events": "ralfia:read",
    "summarize_self_heal_incidents": "ralfia:read",
    "list_self_heal_incidents": "ralfia:read",
    "list_self_heal_baselines": "ralfia:read",
    "save_self_heal_baseline": "ralfia:write",
    "search_email_archive": "ralfia:read",
    "get_email_archive_status": "ralfia:read",
    "get_email_archive_message": "ralfia:read",
    "list_ops_contacts": "ralfia:read",
    "save_whatsapp_group": "ralfia:write",
    "list_whatsapp_groups": "ralfia:read",
    "resolve_whatsapp_group": "ralfia:read",
    "list_whatsapp_groups": "ralfia:read",
    "save_whatsapp_group": "ralfia:write",
    "save_ops_contact": "ralfia:write",
    "send_whatsapp_message": "ralfia:write",
    "send_whatsapp_document": "ralfia:write",
    "send_whatsapp_status": "ralfia:write",
    "generate_video_content": "ralfia:write",
    "publish_video_content": "ralfia:write",
    "video_pipeline_health": "ralfia:read",
    "list_video_voices": "ralfia:read",
    "send_whatsapp_draft": "ralfia:write",
    "search_memory": ["ralfia:memory:read", "ralfia:private_memory"],
    "capture_backlog_item": "ralfia:write",
    "finalize_session_handoff": "ralfia:write",
    "list_dev_backlog": "ralfia:read",
    "update_dev_backlog_item": "ralfia:write",
    "get_dev_backlog_summary": "ralfia:read",
    "send_daily_backlog_whatsapp": "ralfia:write",
    "run_backlog_steward": "ralfia:write",
    "classify_knowledge_seed": "ralfia:read",
    "get_publish_logs": "ralfia:read",
    "save_message": "ralfia:write",
    "save_idea": "ralfia:write",
    "save_pipeline_draft": "ralfia:write",
    "queue_pipeline_item": "ralfia:write",
    "save_chatgpt_note": "ralfia:write",
    "save_chatgpt_handoff": "ralfia:write",
    "save_chatgpt_draft": "ralfia:write",
    "write_agent_message": "ralfia:write",
    "save_memory": ["ralfia:memory:write", "ralfia:private_memory"],
    "save_conversation_batch": ["ralfia:memory:write", "ralfia:private_memory"],
    "finalize_conversation": ["ralfia:memory:finalize", "ralfia:private_memory"],
    "update_memory": ["ralfia:memory:write", "ralfia:private_memory"],
    "get_current_state": ["ralfia:memory:read", "ralfia:private_memory"],
    "update_current_state": ["ralfia:memory:write", "ralfia:private_memory"],
    "get_person_context": ["ralfia:memory:read", "ralfia:private_memory"],
    "correct_memory": "ralfia:admin",
    "forget_memory": "ralfia:admin",
    "resolve_pending_item": ["ralfia:memory:write", "ralfia:private_memory"],
    "timeline": ["ralfia:memory:read", "ralfia:private_memory"],
    "get_memory_review_queue": "ralfia:admin",
    "migrate_daily_memory": "ralfia:admin",
    "save_knowledge_seed": "ralfia:write",
    "list_local_models": "ralfia:read",
    "local_model_health": "ralfia:read",
    "classify_task_runtime": "ralfia:read",
    "get_ai_usage_report": "ralfia:read",
    "cognitive_kernel_check": "ralfia:read",
    "local_exec_inspect_repo": "ralfia:read",
    "local_exec_inspect_remotes": "ralfia:read",
    "local_exec_verified_git_author_status": "ralfia:read",
    "local_exec_repo_policy_status": "ralfia:read",
    "local_exec_repo_authorize": "ralfia:agents",
    "local_exec_repo_revoke": "ralfia:agents",
    "dev_swarm_scope_status": "ralfia:read",
    "dev_swarm_launch_task": "ralfia:agents",
    "dev_swarm_scheduler_status": "ralfia:read",
    "dev_swarm_scheduler_start": "ralfia:agents",
    "dev_swarm_scheduler_stop": "ralfia:agents",
    "dev_swarm_scheduler_tick": "ralfia:agents",
    "dev_swarm_create_fixture_tasks": "ralfia:agents",
    "dev_swarm_executor_status": "ralfia:read",
    "dev_swarm_executor_tick": "ralfia:agents",
    "external_repair_agent_status": "ralfia:read",
    "external_repair_agent_claim_next": "ralfia:agents",
    "external_repair_agent_reconcile": "ralfia:agents",
    "external_repair_agent_run_task": "ralfia:agents",
    "external_repair_run_start": "ralfia:agents",
    "external_repair_run_checkpoint": "ralfia:agents",
    "external_repair_run_complete": "ralfia:agents",
    "external_repair_run_recover": "ralfia:read",
    "browser_session_start": "ralfia:agents",
    "browser_session_status": "ralfia:read",
    "browser_session_action": "ralfia:agents",
    "browser_session_stop": "ralfia:agents",
    "local_exec_prepare_repo": "ralfia:agents",
    "local_exec_hydrate_repo": "ralfia:agents",
    "local_exec_acquire_lock": "ralfia:agents",
    "local_exec_release_lock": "ralfia:agents",
    "local_exec_create_worktree": "ralfia:agents",
    "local_exec_apply_patch": "ralfia:agents",
    "local_exec_write_file": "ralfia:agents",
    "local_exec_run_command_allowlisted": "ralfia:agents",
    "local_exec_commit_branch": "ralfia:agents",
    "local_exec_push_branch": "ralfia:agents",
    "local_exec_configure_remote": "ralfia:agents",
    "local_exec_amend_commit_author": "ralfia:agents",
    "local_exec_report_evidence": "ralfia:agents",
    "local_fs_policy": "ralfia:read",
    "local_fs_list": "ralfia:read",
    "local_fs_read_file": "ralfia:read",
    "local_fs_mkdir": "ralfia:agents",
    "local_fs_write_file": "ralfia:agents",
    "local_fs_move_to_quarantine": "ralfia:agents",
    "local_git_init_repo": "ralfia:agents",
    "local_github_status": "ralfia:read",
    "local_github_create_repo": "ralfia:agents",
    "local_project_bootstrap": "ralfia:agents",
    "mcp_version": "ralfia:read",
    "list_mcp_capabilities": "ralfia:read",
    "describe_tool": "ralfia:read",
    "system_debug": "ralfia:read",
    "diagnose_mcp_session": "ralfia:read",
    "run_local_model": "ralfia:write",
    "route_ai_task": "ralfia:write",
    "generate_daily_brief": "ralfia:write",
    "route_mcp_tools": "ralfia:read",
    "product_intelligence": "ralfia:write",
    "update_pipeline_status": "ralfia:write",
    "log_coordination_event": "ralfia:write",
    "approve_pipeline_draft": "ralfia:write",
    "publish_pipeline_item": "ralfia:write",
    "translate_pipeline_draft": "ralfia:write",
    "generate_draft_image": "ralfia:write",
    "upload_draft_media": "ralfia:write",
    "save_dalle_image": "ralfia:write",
    "save_orchestration_brief": "ralfia:write",
    "handoff_brief": "ralfia:write",
    "save_and_handoff_brief": "ralfia:write",
    "list_pending_handoffs": "ralfia:read",
    "create_orchestration_task": "ralfia:write",
    "dispatch_orchestration_tasks": "ralfia:write",
    "list_orchestration_tasks": "ralfia:read",
    "mark_task_done": "ralfia:write",
    "start_agent_task": "ralfia:write",
    "finish_agent_task": "ralfia:write",
    "list_recent_agent_activity": "ralfia:read",
    "list_service_registry": "ralfia:read",
    "run_service_watchdog": "ralfia:admin",
    "run_recovery_drill": "ralfia:admin",
    "list_ralphia_agents": "ralfia:read",
    "list_agent_bindings": "ralfia:read",
    "sync_coordination_now": "ralfia:write",
    "discover_new_services": "ralfia:admin",
    "seed_agent_registry": "ralfia:admin",
    "detect_missing_handoff": "ralfia:read",
    "register_asset": "ralfia:write",
    "list_assets": "ralfia:read",
    "attach_asset_to_pipeline": "ralfia:write",
    "approve_discovered_service": "ralfia:admin",
    "documentary_state": "ralfia:read",
    "list_recent_changes": "ralfia:read",
    "register_change": "ralfia:write",
    "sync_documentation_now": "ralfia:write",
    "sync_creator_os_projects": "ralfia:write",
    "get_creator_os_project_map": "ralfia:read",
    "get_contifico_status": "ralfia:read",
    "contifico_capabilities": "ralfia:read",
    "list_contifico_personas": "ralfia:read",
    "list_contifico_documentos": "ralfia:read",
    "list_contifico_banco_movimientos": "ralfia:read",
    "sync_contifico_snapshot": "ralfia:read",
    "import_contifico_all": "ralfia:read",
    "import_contifico_full_sync": "ralfia:read",
    "get_contifico_sync_status": "ralfia:read",
    "contifico_inventory_summary": "ralfia:read",
    "normalize_contifico_all": "ralfia:write",
    "link_contifico_personas_to_crm": "ralfia:write",
    "backfill_contifico_orphan_personas": "ralfia:write",
    "normalize_contifico_ledger": "ralfia:write",
    "list_contifico_bank_accounts": "ralfia:read",
    "get_contifico_bank_balance": "ralfia:read",
    "search_contifico_bank_movements": "ralfia:read",
    "search_contifico_transactions": "ralfia:read",
    "search_contifico_accounts": "ralfia:read",
    "query_contifico_stats": "ralfia:read",
    "search_contifico_documents": "ralfia:read",
    "get_contifico_client_summary": "ralfia:read",
    "resolve_contifico_persona": "ralfia:read",
    "contifico_analytics_capabilities": "ralfia:read",
    "contifico_resolve_entity": "ralfia:read",
    "contifico_query": "ralfia:read",
    "contifico_get_document": "ralfia:read",
    "contifico_get_party_360": "ralfia:read",
    "contifico_explain_metric": "ralfia:read",
    "refresh_capability_registry_shadow": "ralfia:write",
    "get_capability_registry_summary": "ralfia:read",
    "get_mcp_profile": "ralfia:read",
    "get_notion_status": "ralfia:read",
    "get_notion_schema_blueprint": "ralfia:read",
    "search_notion_pages": "ralfia:read",
    "preview_notion_sync": "ralfia:read",
    "bootstrap_notion_coordination_db": "ralfia:write",
    "get_notion_coordination_contract": "ralfia:read",
    "notion_upsert_doc_metadata": "ralfia:write",
    "notion_push_doc": "ralfia:write",
    "notion_append_audit_event": "ralfia:write",
    "push_coordination_doc_to_notion": "ralfia:write",
    "add_notion_page_comment": "ralfia:write",
    "get_notion_sync_log": "ralfia:read",
    "get_notion_webhook_setup": "ralfia:read",
    "list_pending_projects": "ralfia:read",
    "get_project_reuse_analysis": "ralfia:read",
    "approve_and_develop_project": "ralfia:agents",
    "send_general_email": "ralfia:write",
    "create_web_content": "ralfia:write",
    "update_web_content": "ralfia:write",
    "change_web_content_status": "ralfia:write",
    "list_web_content": "ralfia:read",
    "export_web_content_for_astro": "ralfia:admin",
    "preview_whatsapp_agent_reply": "ralfia:write",
    "list_agents": "ralfia:agents",
    "get_agent": "ralfia:agents",
    "invoke_agent": "ralfia:agents",
    "create_client_draft": "ralfia:write",
    "upsert_client": "ralfia:write",
    "create_site_draft": "ralfia:write",
    "upsert_site": "ralfia:write",
    "create_asset_draft": "ralfia:write",
    "upsert_asset": "ralfia:write",
    "create_visit_draft": "ralfia:write",
    "log_service_visit": "ralfia:write",
    "add_observation": "ralfia:write",
    "attach_media_to_visit": "ralfia:write",
    "attach_media_to_asset": "ralfia:write",
    "register_client_document": "ralfia:write",
    "list_client_documents": "ralfia:read",
    "document_vault_ingest": "ralfia:write",
    "document_vault_register_external": "ralfia:write",
    "document_vault_list": "ralfia:read",
    "document_vault_search": "ralfia:read",
    "document_vault_get": "ralfia:read",
    "document_vault_set_canonical": "ralfia:write",
    "document_vault_versions": "ralfia:read",
    "document_vault_health": "ralfia:read",
    "document_vault_status": "ralfia:read",
    "document_vault_replicate": "ralfia:write",
    "document_vault_export_file": "ralfia:read",
    "record_site_network_snapshot": "ralfia:write",
    "list_site_network_snapshots": "ralfia:read",
    "build_client_360_snapshot": "ralfia:read",
    "extract_fields_from_media": "ralfia:read",
    "link_asset_to_client": "ralfia:write",
    "link_asset_to_site": "ralfia:write",
    "resolve_client": "ralfia:read",
    "resolve_site": "ralfia:read",
    "resolve_asset": "ralfia:read",
    "list_client_sites": "ralfia:read",
    "list_site_assets": "ralfia:read",
    "create_quote_draft": "ralfia:write",
    "update_quote_draft": "ralfia:write",
    "generate_supervisor_report": "ralfia:write",
    "generate_quote_intro": "ralfia:write",
    "render_quote_document": "ralfia:read",
    "send_quote_delivery": "ralfia:write",
    "get_quote_tracking": "ralfia:read",
    "generate_quote_pdf": "ralfia:write",
    "sync_quote_sources": "ralfia:write",
    "resolve_party": "ralfia:read",
    "upsert_party": "ralfia:write",
    "create_payable_draft": "ralfia:write",
    "upsert_payable": "ralfia:write",
    "resolve_payable": "ralfia:read",
    "list_payables_due": "ralfia:read",
    "record_payment": "ralfia:write",
    "accounting_summary": "ralfia:read",
    "create_receivable_draft": "ralfia:write",
    "upsert_receivable": "ralfia:write",
    "list_receivables_open": "ralfia:read",
    "record_collection": "ralfia:write",
    "create_payable_from_whatsapp": "ralfia:write",
    "create_receivable_from_quote": "ralfia:write",
    "vero_dispatch": "ralfia:write",
    "vero_proactive_briefing": "ralfia:write",
    "quote_client": "ralfia:write",
    "invoice_client": "ralfia:write",
    "technical_report_client": "ralfia:write",
    "get_commercial_mission": "ralfia:read",
    "raul_dispatch": "ralfia:write",
    "raul_catalog_status": "ralfia:read",
    "raul_hydrate_catalog": "ralfia:write",
    "create_purchase_draft": "ralfia:write",
    "upsert_purchase": "ralfia:write",
    "list_quote_deliveries": "ralfia:read",
    "upsert_inventory_item": "ralfia:write",
    "record_inventory_movement": "ralfia:write",
    "receive_goods": "ralfia:write",
    "list_inventory": "ralfia:read",
    "save_funding_program": "ralfia:write",
    "list_funding_programs": "ralfia:read",
    "save_funding_application": "ralfia:write",
    "application_get": "ralfia:read",
    "application_list_questions": "ralfia:read",
    "application_search": "ralfia:read",
    "application_history": "ralfia:read",
    "application_export_snapshot": "ralfia:read",
    "application_upsert": "ralfia:write",
    "application_add_or_update_module": "ralfia:write",
    "application_upsert_question_answer": "ralfia:write",
    "application_attach_source": "ralfia:write",
    "application_attach_evidence": "ralfia:write",
    "application_mark_submitted": "ralfia:write",
    "application_migrate_legacy_funding_application": "ralfia:write",
    "list_funding_applications": "ralfia:read",
    "save_funding_credit_account": "ralfia:write",
    "record_funding_consumption": "ralfia:write",
    "link_funding_project": "ralfia:write",
    "get_funding_registry_summary": "ralfia:read",
    "list_mcp_tool_profiles": "ralfia:read",
    "quoteops_get_mission": "ralfia:read",
    "quoteops_get_sourcing_recommendations": "ralfia:read",
    "quoteops_start_or_continue_mission": "ralfia:write",
    "quoteops_upsert_commercial_profile": "ralfia:write",
    "quoteops_add_supplier_offer": "ralfia:write",
    "quoteops_record_extracted_evidence": "ralfia:write",
    "quoteops_review_extracted_evidence": "ralfia:write",
    "quoteops_review_catalog_draft": "ralfia:write",
    "quoteops_update_decision_brief": "ralfia:write",
    "quoteops_upsert_configuration_alternative": "ralfia:write",
    "quoteops_review_configuration_alternative": "ralfia:write",
    "quoteops_select_package": "ralfia:write",
    "quoteops_update_quote": "ralfia:write",
    "quoteops_approve_quote": "ralfia:write",
    "quoteops_register_delivery": "ralfia:write",
}


def _from_dict(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _tool_name(context: MiddlewareContext) -> str | None:
    message = getattr(context, "message", None)
    if isinstance(message, dict):
        return _from_dict(message, "params", "name") or message.get("name")
    params = getattr(message, "params", None)
    if isinstance(params, dict):
        return params.get("name")
    name = getattr(params, "name", None) or getattr(message, "name", None)
    if isinstance(name, str):
        return name
    return None


def _request_headers() -> dict[str, str]:
    headers = get_http_headers(include={"authorization", "x-api-key", "mcp-session-id", "user-agent"}) or {}
    if headers:
        return headers
    try:
        request = get_http_request()
        return {name.lower(): str(value) for name, value in request.headers.items()}
    except RuntimeError:
        return {}


def _session_id(headers: dict[str, str], context: MiddlewareContext) -> str | None:
    sid = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
    if sid:
        return sid
    ctx = getattr(context, "fastmcp_context", None)
    if ctx is not None:
        try:
            sid = ctx.session_id
        except RuntimeError:
            sid = None
        if isinstance(sid, str) and sid:
            return sid
    return None


def _remember_session_auth(session_id: str | None, headers: dict[str, str]) -> None:
    if not session_id:
        return
    creds: dict[str, str] = {}
    api_key = headers.get("x-api-key") or headers.get("X-API-Key")
    auth = headers.get("authorization") or headers.get("Authorization")
    if api_key:
        creds["api_key"] = api_key
    if auth:
        creds["authorization"] = auth
    if not creds:
        return
    _SESSION_AUTH[session_id] = creds
    _SESSION_AUTH_TS[session_id] = time.time()
    if len(_SESSION_AUTH) > _SESSION_AUTH_MAX:
        oldest = sorted(_SESSION_AUTH_TS, key=_SESSION_AUTH_TS.get)[: len(_SESSION_AUTH) - _SESSION_AUTH_MAX]
        for key in oldest:
            _SESSION_AUTH.pop(key, None)
            _SESSION_AUTH_TS.pop(key, None)


def _resolve_headers(context: MiddlewareContext) -> dict[str, str]:
    headers = _request_headers()
    sid = _session_id(headers, context)
    if sid and sid in _SESSION_AUTH:
        cached = _SESSION_AUTH[sid]
        if time.time() - _SESSION_AUTH_TS.get(sid, 0) > _SESSION_AUTH_TTL_SEC:
            _SESSION_AUTH.pop(sid, None)
            _SESSION_AUTH_TS.pop(sid, None)
        else:
            if not (headers.get("x-api-key") or headers.get("X-API-Key")) and cached.get("api_key"):
                headers["x-api-key"] = cached["api_key"]
            if not (headers.get("authorization") or headers.get("Authorization")) and cached.get("authorization"):
                headers["authorization"] = cached["authorization"]
    _remember_session_auth(sid, headers)
    return headers


class ApiKeyMiddleware(Middleware):
    def __init__(self, valid_key: str) -> None:
        self.valid_key = (valid_key or "").strip()

    async def on_request(self, context: MiddlewareContext, call_next):
        _resolve_headers(context)
        return await call_next(context)

    async def on_initialize(self, context: MiddlewareContext, call_next):
        _resolve_headers(context)
        return await call_next(context)

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = _resolve_headers(context)
        tool_name = _tool_name(context) or "unknown_tool"
        session_id = _session_id(headers, context)
        user_agent = headers.get("user-agent") or headers.get("User-Agent")
        raw_required = TOOL_SCOPES.get(tool_name, "ralfia:read")
        required_scopes = [raw_required] if isinstance(raw_required, str) else list(raw_required)
        api_key = headers.get("x-api-key") or headers.get("X-API-Key")
        if self.valid_key and api_key and api_key == self.valid_key:
            return await call_next(context)

        auth = headers.get("authorization") or headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            token_doc = validate_access_token(token)
            if token_doc:
                token_scopes = set((token_doc.get("scope") or "").split())
                token_resource = token_doc.get("resource")
                if token_resource and token_resource != OAUTH_MCP_RESOURCE:
                    raise ToolError("Unauthorized: OAuth resource mismatch")
                if set(required_scopes).issubset(token_scopes) or "ralfia:admin" in token_scopes:
                    return await call_next(context)
                mongo_store.log_mcp_error(
                    error_type="missing_scope",
                    tool=tool_name,
                    session_id=session_id,
                    client=user_agent,
                    message=f"Missing scope(s) {' '.join(required_scopes)} for {tool_name}",
                    catalog_version=None,
                    scopes=sorted(token_scopes),
                    metadata={"required_scopes": required_scopes},
                )
                raise ToolError(f"missing_scope: {' '.join(required_scopes)}")
            mongo_store.log_mcp_error(
                error_type="invalid_oauth_token",
                tool=tool_name,
                session_id=session_id,
                client=user_agent,
                message=f"Invalid or expired bearer token for {tool_name}",
                catalog_version=None,
                scopes=[],
            )
            if self.valid_key:
                raise ToolError("Unauthorized: valid X-API-Key or OAuth Bearer token required")
            raise ToolError("Unauthorized: OAuth Bearer token required")

        if self.valid_key:
            mongo_store.log_mcp_error(
                error_type="unauthorized",
                tool=tool_name,
                session_id=session_id,
                client=user_agent,
                message=f"Missing credentials for {tool_name}",
                catalog_version=None,
                scopes=[],
            )
            raise ToolError("Unauthorized: valid X-API-Key or OAuth Bearer token required")

        mongo_store.log_mcp_error(
            error_type="unauthorized",
            tool=tool_name,
            session_id=session_id,
            client=user_agent,
            message=f"Missing OAuth bearer token for {tool_name}",
            catalog_version=None,
            scopes=[],
        )
        raise ToolError("Unauthorized: OAuth Bearer token required")
