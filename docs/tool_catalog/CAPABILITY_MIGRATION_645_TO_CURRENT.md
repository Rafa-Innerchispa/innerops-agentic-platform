# Capability Migration 645 To Current

Date: 2026-09-07
Task: ops_53a63b0f59af
Correlation: mcp-short-second-connector-verification-20260907

This matrix classifies the 45 historical tool names reported by the live catalog guard when the MCP surface moved from 645 to 609 tools. The repair does not silence the guard by changing the baseline. It restores compatible public names where a current backend exists and, after the post-audit in `ops_23dce3623c9a`, routes the seven previously fail-closed names to safe verified equivalents.

Future removals must be owner-approved. `mcp_diagnostics._catalog_guard()` now returns `needs_owner_approval=true` and lists `unapproved_removed_tools` when a tool disappears without an explicit owner-approved retirement record. It also treats `tool_name_present=true` plus an unavailable backend as a capability regression unless the retirement is explicitly approved by the owner.

## Summary

- RESTORE: backend still exists and the tool was restored as a real callable surface.
- REPLACED_COMPATIBLE: the historical name is restored as an alias/wrapper over a modern safe surface.
- UNAVAILABLE/RETIREMENT_PENDING: no compatible backend is available. This requires explicit owner approval before the catalog can accept it.

## Matrix

| Tool | Status | Replacement | Evidence |
| --- | --- | --- | --- |
| agent_iskcon_action | REPLACED_COMPATIBLE | agent_iskcon_dispatch | AG-52 backend exists. |
| agent_iskcon_artifact_download | REPLACED_COMPATIBLE | module_contract.download_module_artifact | Module artifact backend exists on live nodes; wrapper falls back closed if absent. |
| agent_iskcon_class_update | RESTORE | agent_iskcon_class_update | AG-52 safe draft backend restored. |
| agent_iskcon_module_manifest | REPLACED_COMPATIBLE | agent_iskcon_capabilities | AG-52 capabilities backend exists. |
| agent_iskcon_sources | RESTORE | agent_iskcon_sources | AG-52 source summary backend restored. |
| agent_iskcon_yoga_campaign | RESTORE | agent_iskcon_yoga_campaign | AG-52 safe draft backend restored. |
| digitalocean_mi325x_deploy_plan | REPLACED_COMPATIBLE | digitalocean_preflight | DigitalOcean provider backend exists; execution remains approval-gated. |
| disk_steward_cleanup_verified | REPLACED_COMPATIBLE | disk_steward.cleanup_verified | Verifies executed move metadata and finalizes state without deleting files. |
| disk_steward_execute_migration | RESTORE | disk_steward.confirm_move | Disk Steward proposal execution backend exists and requires sender approval. |
| disk_steward_inventory | RESTORE | disk_steward.build_status | Disk Steward inventory backend exists. |
| disk_steward_plan_migration | RESTORE | disk_steward.create_move_proposal | Disk Steward proposal backend exists. |
| disk_steward_update_backup_policy | REPLACED_COMPATIBLE | disk_steward.update_backup_policy | Validates backup policy and can persist safe policy state; dry-run by default. |
| disk_steward_verify_migration | RESTORE | disk_steward.build_status | Read-only verification snapshot. |
| editorial_image_providers | RESTORE | editorial_store.REAL_IMAGE_PROVIDERS | Editorial provider metadata exists. |
| get_disk_steward_status | RESTORE | disk_steward.build_status | MCP function existed but catalog entry was missing. |
| identify_agent_session | RESTORE | agent_identity.normalize_actor | Canonical identity backend exists. |
| inneros_agent_fabric_status | REPLACED_COMPATIBLE | a2a_status/provider_execution_fabric_status/resource_fabric_status | Modern fabric is split across newer surfaces. |
| inneros_dual_deployment_drill | REPLACED_COMPATIBLE | ag43_platform_sync_agent.run_failover_dry_run | Dual deployment drill is backed by the AG-43 failover dry-run path. |
| inneros_dual_deployment_status | REPLACED_COMPATIBLE | mcp_fleet.fleet_status | Dual deployment status is backed by live fleet status probing. |
| inneros_dual_queue_operation | REPLACED_COMPATIBLE | durable_coordination_spine.publish_event | Dual queue operation is backed by typed durable coordination events; dry-run uses an in-memory sink. |
| inneros_dual_reconcile_operations | REPLACED_COMPATIBLE | ag40_runtime_reconciler.reconcile_runtime_state | Dual reconcile routes to the runtime reconciler in dry-run mode by default. |
| inneros_ingest_drop_run | RESTORE | ingest_drop_folder.run | Backend exists on live nodes. |
| inneros_ingest_drop_status | RESTORE | ingest_drop_folder.status | Backend exists on live nodes. |
| judge_console_content_get | RESTORE | judge_console_content.get_content | Backend exists on live nodes. |
| judge_mi325x_deploy | REPLACED_COMPATIBLE | digitalocean_amd_provider.preflight/create_gpu_droplet(dry_run) | Judge MI325X deploy routes to preflight or approval-gated dry-run create; no cloud spend by default. |
| judge_model_routing_policy | RESTORE | judge_console_content.model_routing_policy | Backend exists on live nodes; wrapper falls back to local model health. |
| judge_resource_telemetry | RESTORE | judge_telemetry.resource_telemetry | Backend exists on live nodes. |
| judge_safe_trigger | RESTORE | judge_telemetry.safe_judge_trigger | Backend exists on live nodes; dry-run remains default. |
| judge_trace_current | RESTORE | judge_telemetry.current_trace | Backend exists on live nodes. |
| judge_trace_detail | RESTORE | judge_telemetry.trace_detail | Backend exists on live nodes. |
| judge_trace_history | RESTORE | judge_telemetry.list_trace_events | Backend exists on live nodes. |
| judge_trace_kpis | RESTORE | judge_telemetry.kpis | Backend exists on live nodes. |
| judge_trace_record | RESTORE | judge_telemetry.record_trace_event | Backend exists on live nodes. |
| judge_workflow_continue | RESTORE | judge_workflows.continue_workflow | Backend exists on live nodes. |
| judge_workflow_execute | RESTORE | judge_workflows.execute_workflow | Backend exists on live nodes. |
| judge_workflow_get | RESTORE | judge_workflows.get_workflow | Backend exists on live nodes. |
| judge_workflow_list | RESTORE | judge_workflows.list_workflows | Backend exists on live nodes. |
| judge_workflow_start | RESTORE | judge_workflows.start_workflow | Backend exists on live nodes. |
| list_self_heal_baselines | RESTORE | self_heal_metrics.list_self_heal_baselines | Self-heal ledger backend exists. |
| list_self_heal_incidents | RESTORE | self_heal_metrics.list_self_heal_incidents | Self-heal ledger backend exists. |
| module_action | RESTORE | module_contract.route_module_action | Backend exists on live nodes; dry-run remains default. |
| module_artifact_download | RESTORE | module_contract.download_module_artifact | Backend exists on live nodes. |
| module_manifest | RESTORE | module_contract.get/list_module_manifest(s) | Backend exists on live nodes. |
| save_self_heal_baseline | RESTORE | self_heal_metrics.save_service_baseline | Self-heal ledger backend exists. |
| summarize_self_heal_incidents | RESTORE | self_heal_metrics.summarize_self_heal_incidents | Self-heal ledger backend exists. |
