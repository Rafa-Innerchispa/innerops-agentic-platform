# InnerOS Control-Plane Continuity

Last updated: 2026-09-06

This note records the current operating contract for the InnerOS agentic
control-plane so a new ChatGPT, Codex, Cursor, Antigravity, or local-agent
session can continue from GitHub and MCP state instead of relying on a long
chat transcript.

## Current Public Source

- Canonical repo: `Rafa-Innerchispa/innerops-agentic-platform`
- Visibility checked on 2026-09-06: public
- Current main after control-plane sync: `d4926dd7d04fd8b1749d4104209411fee6338374`
- Durable spine branch retained for audit: `codex/durable-spine-sync-20260906`

The public repository is intended to show the real engineering work. Secrets,
tokens, private customer data, private memory, internal IP-only operational
details, and credentials must stay out of GitHub.

## Durable Coordination Spine

The control-plane now has a durable coordination spine composed of:

- MCP/A2A as the model-facing tool and agent communication surface.
- Mongo-backed `ops_tasks`, agent messages, evidence, ownership, revisions, and
  status transitions as the operational truth.
- RACB locks for repo/worktree ownership before mutation.
- NATS JetStream for durable event publication and replay.
- Temporal for durable workflows and retryable long-running orchestration.
- OpenTelemetry for traces and telemetry correlation.

Validated live on Intel `.4` and AMD `.5`:

- MCP service active on both nodes.
- NATS JetStream stream `INNEROS_COORDINATION` accepts events.
- Temporal health probes pass.
- OTel exports through OTLP and flushes successfully.
- `dev_swarm_repo_inference` focused regression passes from runtime and main.

Important boundary: the spine is live, but every product workflow still needs
to adopt it explicitly. A feature is not considered migrated just because the
spine exists.

## Anti-Loop Rules

To avoid repeating the same repair loop:

1. Do not treat a runtime-only fix as complete if GitHub `main` or a tracked
   release branch still points at stale code.
2. Do not treat a code change as complete if the MCP-visible schema does not
   expose the new capability.
3. Do not treat queued, delivered, spawned, or `codex --version` as execution.
   Completion requires task evidence.
4. Do not mutate an AMD workspace when it is on another agent's dirty branch.
   Use RACB, a worktree, or a safe fast-forward on the canonical workspace.
5. Do not merge local-agent output that rewrites large control-plane files
   without passing the diff-risk guard.
6. Keep public demos read-only unless explicit owner approval gates execution.

## Required Completion Gate

For control-plane changes, PASS requires:

- isolated branch or worktree;
- RACB lock during mutation;
- focused regression tests;
- compile/check step appropriate to the repo;
- evidence in `ops_tasks` or agent message;
- Git commit SHA;
- GitHub push or explicit reason why it could not be pushed;
- runtime verification on Intel and AMD when the change affects shared runtime;
- no exposed secrets.

## MCP Catalog Performance

Large flat MCP catalogs slow normal ChatGPT sessions. The desired contract is:

- expose a small default catalog first;
- route by intent/profile (`coding`, `memory`, `browser`, `cloud`, `github`,
  `gitlab`, `ops`, `finance`, `domains`, `notifications`);
- expand tools only after discovery identifies the needed profile;
- keep local-first execution tools available through bounded wrappers, not
  arbitrary shell;
- prefer local workers for long tests, scans, and repetitive verification.

The next implementation step is a `Tool Catalog Router` that makes ChatGPT see
capability groups rather than hundreds of raw tools.

## Current Follow-Ups

- `ops_526a216683ba`: expose `base_ref` and `expected_sha` in the visible
  `project_runtime_bootstrap` schema. ChatGPT owns this unless reassigned.
- Tool catalog/profile routing: reduce ChatGPT latency by presenting compact
  profile-specific tool surfaces.
- Drift guardian: automatically compare GitHub main, Intel workspace, AMD
  workspace, Intel runtime, and AMD runtime.
- Safe fast-forward guardian: when a tested branch can advance main without
  conflict, either perform the fast-forward or create an explicit approval task.
- Task janitor: close stale duplicates and superseded tasks without deleting
  evidence.

## New Session Start

Start from live coordination, not memory:

1. Read `get_coordination_live()`.
2. Read open `ops_tasks` for the target agent.
3. Check RACB locks before editing.
4. Check GitHub `main` and the relevant runtime path.
5. Use local agents and local servers first.
6. Report every terminal result back to MCP with commit, tests, and blockers.
