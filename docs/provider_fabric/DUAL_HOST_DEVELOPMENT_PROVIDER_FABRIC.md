# Dual Host Development Provider Fabric

Status: Phase B/D baseline contract, local-first, no secrets.

## Purpose

InnerOS must treat development capacity as host-specific provider instances, not as one abstract `codex`, `cursor`, or `antigravity` bucket. This prevents stale claims, false dispatch, and hidden manual-session requirements.

## Provider Instances

The canonical instances are:

- `codex.amd5`
- `codex.intel4`
- `cursor.amd5`
- `cursor.intel4`
- `antigravity.amd5`
- `antigravity.intel4`
- `qwen.amd5`
- `local.intel4`

Each instance exposes only non-secret fields: `host`, `provider`, `installed`, `authenticated`, `headless_ready`, `inneros_dispatchable`, `account_profile`, `usage_available`, `last_heartbeat`, `current_task`, `repo_lock`, `model_runtime`, `auth_mode`, and `reason_codes`.

## Truth Boundary

Installed does not mean authenticated. Authenticated does not mean headless ready. Headless ready does not mean safe to dispatch without repo locks, package-root policy, quality gates, and evidence capture.

Codex, Cursor, and Antigravity are marked `inneros_dispatchable=false` until a supported headless execution contract proves readiness on the specific host. They remain valid manual or assisted development surfaces.

`qwen.amd5` is the first local coding route because it is a resident local runtime behind vLLM/ROCm10. `local.intel4` is the first local orchestration/test/build fallback through the Local Execution Plane.

## Routing Policy

Default routing is local-first:

1. Use `qwen.amd5` for repetitive coding, bounded edits, draft implementations, and low-cost iteration.
2. Use `local.intel4` for repository orchestration, tests, build checks, browser-adjacent validation, and fallback work.
3. Use Codex/Cursor/Antigravity only when an IDE or external repair agent is explicitly required and the instance is known available.
4. Use cloud burst only when local capacity or capability is insufficient and an approval gate is active.

Reason codes are: `local_first`, `capacity_available`, `provider_required`, `host_affinity`, `repo_locality`, `quality_gate`, `fallback`, and `manual_session_required`.

## Live Inventory Snapshot

2026-09-07 read-only probe:

- Intel `.4` responded over SSH; MCP user services `ralfia-mcp.service` and `ralfia-mcp-profile@chatgpt_compact.service` were active; `codex-cli 0.130.0` was visible in the non-interactive PATH; local Ollama API was not reachable on `127.0.0.1:11434`.
- AMD `.5` responded over SSH; MCP user services were active; vLLM on `127.0.0.1:8000` reported `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ`; Codex/Cursor/Antigravity were not visible in the non-interactive PATH used by the probe.

This snapshot is evidence, not a permanent truth. Runtime health should be refreshed by status tools before dispatch.

## MCP Entry Points

- `resource_fabric_status` returns the provider instance schema and inventory.
- `resource_fabric_route_development_provider` selects a host-specific development provider and returns reason codes.
- `dev_swarm_launch_task` remains the safe launcher for owner-approved repo worktrees.

