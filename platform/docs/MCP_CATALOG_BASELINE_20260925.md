# MCP Catalog Baseline Reconciliation (2026-09-25)

## 1. Context & Scope
Audit of InnerOS MCP tool catalog transition from legacy baseline (654 tools) to canonical production catalog (682 tools).

## 2. Classification of Tool Removals (Intentional Deprecations)
The following 4 tools were intentionally removed from the active MCP catalog:
- `local_github_pin_repositories`: Consolidated into unified repository and portfolio management.
- `local_github_professionalization_audit`: Replaced by `local_github_audit_suite`.
- `local_github_update_owner_profile`: Replaced by `local_github_profile_status` and unified identity management.
- `local_github_update_repo_profile`: Consolidated into standard GitHub repository configuration operations.

**Conclusion:** No accidental loss. All 4 removals represent intentional architectural consolidations.

## 3. Tool Additions (24 Canonical Capabilities)
- Task Leases & Coordination: `acquire_task_lease`, `release_task_lease`, `renew_task_lease`, `get_coordination_liveness_summary`, `reconcile_coordination_liveness`.
- Universal Bootstrap & Session Guard: `enroll_device_bootstrap`, `get_universal_bootstrap_plan`, `session_guard_check_mutation`, `session_guard_ensure_bootstrap`, `session_guard_watchdog`, `universal_agent_bootstrap`.
- Smart Home / Hubitat: `hubitat_discover`, `hubitat_find_device`, `hubitat_get_device`, `hubitat_list_devices`, `hubitat_ping`, `hubitat_send_command`, `hubitat_status`.
- GitLab ContributorOps: `local_gitlab_get_job_trace`, `local_gitlab_get_merge_request`, `local_gitlab_list_merge_request_discussions`, `local_gitlab_list_merge_request_pipelines`, `local_gitlab_list_pipeline_jobs`.
- Routing: `probe_route_access_plane`.

## 4. MCP Profile Strategy
- **Compact Profile (`chatgpt_compact`)**: 15 bounded tools for fast discovery, coordination, and sub-agent dispatch without prompt bloat.
- **Full Catalog (`ralfia_full`)**: 682 tools across business, engineering, infrastructure, and multimedia capabilities.
