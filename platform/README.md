# InnerOS Agentic Platform

Canonical runtime for the InnerOS/Ralphi IA MCP ecosystem.

This repository is no longer the old temporary `raphiia-openai` project under `/home/rlopez/projects`. The active platform lives in the InnerOS core tree and is shared by the two local servers as one logical ecosystem.

## Canonical Locations

| Item | Current value |
|------|---------------|
| Canonical root | `/home/rlopez/inneros/inneros_core` |
| Platform package | `/home/rlopez/inneros/inneros_core/platform` |
| Live MCP service | `ralfia-mcp.service` |
| MCP port | `8102` |
| Health/app service | `ralfia-app.service` on `8101` |
| Primary logical model | one MCP catalog, two execution planes |

## Live Topology

| Node | Address | Role |
|------|---------|------|
| Intel | `192.168.1.4` | business workflows, memory, coordination, Contifico, WhatsApp, fallback plane |
| AMD | `192.168.1.5` | GPU workloads, voice/media, vLLM canary, Home Assistant proxy, high-compute plane |

The public and local clients should see this as one MCP ecosystem. Routing should select the best execution plane by capability, then fail over to the peer when safe.

## Verified Release State - 2026-08-30

- Runtime commit: `e590ea24f160ab66e60599c238a3ebf842817027`.
- Branch used for consolidation: `release/inneros-platform-20260830`.
- A2A bridge: online through the InnerOS coordination transport.
- A2A agent cards: `58` verified by live probe.
- Fleet status after selective sync: AMD and Intel MCP are reachable and runtime fingerprints are consistent.
- Judge Console backend content: `6` persisted sections available through MCP.
- Drop-folder ingest root: `/home/rlopez/data/inneros_ingest`.
- Qdrant collections observed: `docvault`, `inneros_kb`.
- MI325X/DigitalOcean cloud burst remains approval gated; dry-run/preflight only unless owner confirms an apply window.
- Google/Gemma model routing is represented in `judge_model_routing_policy`; use live probes before claiming a specific external quota or model is available.
- AMD has an active `inneros-vllm-canary-rocm10.service`, but the host-level `/opt/rocm` toolchain observed during consolidation reports ROCm 7.2.1. Treat ROCm10 as canary/service-scoped until a separate system-level ROCm10 verification proves otherwise.
- Lemonade service observed active as `lemonade-lemond.service`.

## Release Rules

- Do not deploy production from this branch without review.
- Do not touch Workforce product code, `femar`, `workforce.pcdoctor.ai`, Judge UI, ISKCON UI, or Cursor-owned work while consolidating platform release hygiene.
- Do not run broad `rsync --delete` from a dirty tree. Use selective sync or a clean release branch.
- Runtime/cache/worktree artifacts under `var/`, `tmp/`, `platform/var/`, and generated local execution worktrees are not release code.
- MCP tools that execute commands must stay allowlisted, typed, rooted in approved package roots, idempotent, and evidence-producing.
- Public demos are read-only unless protected by OAuth/Cloudflare Access or explicit owner approval.

## Verification Commands

Run from the server, not from Windows:

```bash
cd /home/rlopez/inneros/inneros_core
PYTHONPATH=platform platform/venv/bin/python3 -m pytest -q platform/tests
systemctl --user status ralfia-mcp.service --no-pager
```

For a clean release worktree that does not include its own virtualenv, use the canonical virtualenv:

```bash
cd /home/rlopez/inneros/inneros_core/worktrees/release-inneros-platform-20260830
PYTHONPATH=platform /home/rlopez/inneros/inneros_core/platform/venv/bin/python3 -m pytest -q platform/tests
```

## Key MCP Surfaces

| Surface | Purpose |
|---------|---------|
| `a2a_status`, `a2a_agent_cards`, `a2a_dispatch`, `a2a_task_status` | Durable A2A facade over InnerOS coordination/RACB |
| `judge_console_content_get` | Backend content contract for Judge Console |
| `judge_model_routing_policy` | Local/cloud model routing policy snapshot |
| `digitalocean_mi325x_deploy_plan` / `judge_mi325x_deploy` | Approval-gated MI325X burst planning |
| `inneros_ingest_drop_status`, `inneros_ingest_drop_run` | Drop-folder ingestion into Document Vault/Qdrant |
| `get_mcp_fleet_status`, `sync_platform_to_intel` | Fleet health and controlled platform sync |

## Coordination

Coordination truth is live MCP/Mongo state, not stale Markdown mirrors. Agents should start by reading `get_coordination_live()` and their inbox, then acknowledge the current revision before taking ownership.
