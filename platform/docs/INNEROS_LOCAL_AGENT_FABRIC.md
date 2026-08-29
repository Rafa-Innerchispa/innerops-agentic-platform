# InnerOS Local Agent Fabric

InnerOS treats the Intel and AMD hosts as one logical MCP ecosystem with two execution planes.

- Intel `.4`: coordination, memory, business services, Home Assistant primary, WhatsApp, email, and fallback tests.
- AMD `.5`: local coding/reasoning workers, vLLM/GPU workloads, media/browser-heavy tasks, and secondary MCP runtime.
- GitHub remains the canonical source repository for project code.
- GitLab is a secondary mirror for visibility, collaboration, and CI experiments until explicitly promoted.

## Execution Flow

1. An `ops_task` is created with `correlation_id`, assignee, priority, checklist, and evidence requirements.
2. AG-25/dispatcher resolves the canonical repo and checks owner approval, scopes, and priority.
3. The local execution plane acquires a repo lock and creates an isolated worktree.
4. Local models are preferred for implementation. External/Codex providers are used only for repair or approved escalation.
5. Writes are bounded by repo policy and package roots. Arbitrary shell is not opened.
6. Tests/build/lint run inside the isolated worktree or approved package root.
7. Evidence is reported to Mongo/RACB. PASS requires real code, tests, and evidence, not scaffold-only contracts.
8. Verified changes are committed, integrated to GitHub, mirrored to GitLab, and recorded in the productivity ledger.

## Auto-Dispatch And Repair

The External Repair Agent runs as a persistent daemon. Auto-claim is enabled only when both:

- `EXTERNAL_REPAIR_AUTO_CLAIM=1`
- `EXTERNAL_REPAIR_OWNER_AUTHORIZED=1`

The daemon reconciles terminal handoffs, stale runs, and provider-idle states. It only claims a next task when the provider is ready, no active run exists, and no recent `accepted`/`in_progress` task is already owned by that provider. Old blocked/verification tasks do not freeze the queue.

## Home Assistant Control Plane

Home Assistant registry changes use the official WebSocket API with `HOME_ASSISTANT_TOKEN` server-side. Tokens are not exposed in evidence. The normal path is friendly/device names only:

- `ha_list_devices`
- `ha_list_entity_registry`
- `ha_rename_device`
- `ha_rename_entity_name`
- `ha_batch_rename`
- `ha_search_entity_references`

`entity_id` changes are rejected by default and require a separate audited flow after reference search.

## Browser Sessions

`browser_session_start` creates a human-in-the-loop Playwright session on the server and returns:

- a local agent URL,
- a LAN URL for Rafael from Windows,
- a public URL only when a configured broker base exists.

`browser_session_action` performs atomic `navigate`, `click`, `type`, `press`, and `wait` operations by `session_id` plus token. Passwords typed by the owner are sent only to the live page and are not persisted by InnerOS.

## Google AI Model Lanes

Google AI is available as governed Resource Fabric lanes, not as a production
default that bypasses local-first routing.

- `google-gemini-primary`: primary Google reasoning lane, currently
  `gemini-2.5-flash` on Vertex AI for project `innerops-agentic-platform`.
- `google-flash-lite-triage`: low-cost classification/triage lane,
  currently `gemini-2.5-flash-lite`.
- `google-memory-embedding`: semantic memory/document retrieval embeddings,
  currently `gemini-embedding-001` with 3072 dimensions.
- `google-gemini-35-bounded-review`: available bounded reviewer lane,
  currently `gemini-3.5-flash-lite` on Vertex AI `global`; use this as the
  Google critic/review path while Gemma access is unavailable.
- `google-gemma-bounded-review`: Gemma critic/reviewer lane. It is registered
  but not default-enabled until the project has live model access; Vertex
  returned 404 for Gemma IDs in `us-central1`/`global` on 2026-08-29.

MCP tools:

- `google_ai_model_allowlist`
- `google_ai_model_lanes_status`
- `google_ai_model_smoke`

Live smoke tests require `allow_live=true`, use gcloud OAuth on the server, and
cap prompts/output to avoid uncontrolled cloud spend.

## Productivity Ledger

`productivity_metrics` is the canonical collection for human-time savings events. Runtime/worker duration is separate from human time saved. Tools:

- `save_productivity_event`
- `list_productivity_events`
- `summarize_productivity_events`

## Current Publication Note

The live runtime checkout at `/home/rlopez/inneros/inneros_core/platform` currently contains the operational MCP runtime. GitHub `main` for `Rafa-Innerchispa/innerops-agentic-platform` points to a different tree shape around commit `23261510547927d33d92b34b4479bd9a60a9bde3`, so direct merge to `main` must not be forced.

Safe publication status:

- Runtime repair branch pushed to GitHub: `codex/ops194-platform-repair`.
- GitLab project exists: `https://gitlab.com/rafagye/innerops-agentic-platform`.
- GitLab must remain a mirror until the platform source-of-truth tree is reconciled.

## Home Assistant Standby Note

Intel `.4` is the active Home Assistant host. Observed runtime:

- image: `ghcr.io/home-assistant/home-assistant:stable`
- HA version: `2026.5.2`
- restart policy: `unless-stopped`
- config mount: `/mnt/datos_agentes/home-assistant/config:/config`
- backup artifact observed: `/config/backups/Custom_backup_2026.5.2_2026-08-26_15.31_18592294.tar`

AMD `.5` has no Home Assistant container currently. Warm standby should be active-passive only: replicate config/backups off `.4`, prepare stopped container on `.5`, and require fencing/manual failover before starting automation there.
