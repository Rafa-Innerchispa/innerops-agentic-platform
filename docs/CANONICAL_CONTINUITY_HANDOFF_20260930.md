# Canonical continuity handoff — MCP Small/Full, agents, dual-node and Bellini

**Date:** 2026-09-30  
**Status:** active recovery handoff; verify live state before acting  
**Canonical repository:** `Rafa-Innerchispa/innerops-agentic-platform`

## Purpose

This is the repository entrypoint for continuing the current recovery from Notion, ChatGPT, Cursor, Antigravity, Codex, or a local agent without relying on chat history. It contains no secrets. Every new operator must compare this document with the current branch, PRs, Notion recovery pages, and live runtime evidence.

## Current architecture decision

- Public entrypoint: `https://mcp.pcdoctor.ai/router/mcp`.
- Public profile: `chatgpt_compact`.
- Public surface observed: 23 direct tools, hard ceiling 25.
- Internal catalog observed: 693 tools/capabilities.
- MCP Small remains fixed and compact.
- MCP Full remains internal/break-glass during migration; do not connect it as a normal 693-tool client.
- New domain needs become internal capabilities/adapters, not new public tools.

Target:

```text
ChatGPT / Notion / Cursor / Antigravity
        -> MCP Small (fixed <=25)
        -> capability search / describe / governed invoke / execution status
        -> OAuth, tenant, site, scopes, risk, approvals, idempotency, audit
        -> A2A + Temporal + Device/Resource Fabric
        -> local agents / providers / MCP Full legacy backend
```

The existing Capability Router F0 selects bounded profiles and tool names. That is not sufficient: an MCP client cannot directly invoke a tool omitted from `tools/list`. The missing component is a universal, allowlisted, server-side invoker. Arbitrary function dispatch is forbidden.

## PROVEN at handoff creation

- MCP Small answers through the canonical connection.
- `chatgpt_compact` projects 23 tools.
- Catalog version `2.68.0`; profile version `1.4.5`; 693 internal tools observed.
- Local scheduler is enabled and reports AMD primary / Intel secondary.
- Device Fabric and Bellini handoff artifacts exist.
- PR #110 was squash-merged to `main` as `41fb55d153494df6b26988e23095328daa3f0f7e`.
- PR #111 remains draft.

## OPEN / FAIL at handoff creation

1. Live `create_agent_message(message_type="task")` persists the message but normalization fails before Temporal with:

   ```text
   create_ops_task() got an unexpected keyword argument 'source_message_id'
   ```

   The repository contains the compatibility fix; the live backend is still executing an older signature or a divergent checkout.

2. Live `route_mcp_tools` fails with:

   ```text
   route_tools() got an unexpected keyword argument 'for_model'
   ```

   This is another schema/runtime deployment mismatch.

3. The strict OAuth audit expects the public 401 challenge to include:

   ```http
   WWW-Authenticate: Bearer resource_metadata="https://mcp.pcdoctor.ai/.well-known/oauth-protected-resource/router/mcp"
   ```

   Keep PR #111 draft until this audit passes.

4. The GitHub integration can write normal repository paths but receives:

   ```text
   403 Resource not accessible by integration
   ```

   for `.github/workflows/*`. The candidate workflow is preserved at `docs/ci/p0-coordination.workflow.yml`. Moving it requires a credential with `workflows` permission or an authorized local push.

5. MCP Full failures have been reported from other chats but were not directly tested from the current Notion connection. Audit Full as an internal backend; do not solve the problem by reconnecting the 693-tool catalog to ChatGPT.

6. The owner reports that Intel/AMD coordination is resolved. Treat that as `CLAIMED` until the acceptance canaries below produce fresh evidence.

## Dual-node acceptance canaries

Do not declare Intel/AMD coordination closed until all are captured:

1. Same approved Git SHA or reproducible deployment manifest on both nodes.
2. Same hashes for profiles, catalog, coordination modules, agent registry, and critical runtime files.
3. Message created through one node remains visible through the other; polling does not ACK by default; explicit ACK is durable.
4. One task admission creates exactly one Temporal workflow using a deterministic workflow ID.
5. A real worker owns the task and provides `run_id`, heartbeat, bounded output, and evidence.
6. Worker restart/failover resumes without duplicate execution or lost state.
7. Agent catalog count/hash agrees on both nodes and one local-first task completes through AMD with Intel fallback tested separately.
8. Rollback and recovery evidence are recorded.

Mongo is a projection, not lifecycle authority. Direct terminal state writes are forbidden.

## MCP Full audit contract

Run a read-only audit and record:

- endpoint, service/unit, checkout path, Git SHA or artifact hash, profile, and node;
- OAuth resource/audience and authorization behavior;
- initialize and `tools/list` result/count;
- schema-to-runtime signature comparison for representative coordination, agent, Device Fabric, and routing tools;
- five bounded read-only sample calls;
- capabilities still reachable only through Full;
- dependency matrix for migrating each capability behind the broker;
- errors with exact status/body but no tokens or secrets.

Full may remain operational as an internal provider. It must not become the normal client surface again.

## Capability Gateway contract

Implement stable public primitives, replacing—not adding on top of—domain-specific direct tools:

1. `capability_search`
2. `capability_describe`
3. `capability_invoke`
4. `capability_execution`

Each manifest must define capability ID/version, provider, input/output schema, scopes, tenant/site policy, risk class, read-only/mutation mode, approval policy, timeout, idempotency, result sanitization, and provenance.

`capability_invoke` may call only registered allowlisted handlers. Client-supplied tenant, site, or approval claims must never override server-derived identity and policy.

Long-running work is admitted through Temporal and returns an `execution_id`. Status, candidate evidence, approval, cancel, and final result use the generic execution contract.

## Bellini I-II rule

During the network review:

- `tenant=bellini`
- `site=bellini-i-ii`
- `mode=read_only`

Do not add public tools such as `get_gcc_arp`, `get_gcc_dhcp`, or `get_hikvision_logs`. Register a capability such as `network.device.query.v1` with sections including `logs`, `dhcp`, `arp`, `vlans`, `mac_table`, `lldp`, `routes`, `clients`, and `health`; resolve provider/credentials/protocol through Device Fabric.

Mutations require an explicit risk transition, approval, dry-run/preflight where possible, and evidence.

## Canonical read order

### Notion

1. `Playbook V2.0 — OS Central`
2. `InnerOps Agentic Platform`
3. `P0 — Reparación sistémica MCP Small, coordinación y dual-node — 2026-09-29`
4. `P0 — Recuperación MCP Small canónico — 2026-09-30`
5. `Handoff canónico — MCP Small/Full, agentes y Bellini — 2026-09-30`

### Repository

1. This file.
2. `docs/P0_COORDINATION_RECOVERY_20260929.md`
3. `docs/MCP_SMALL_CANONICAL_OAUTH_20260930.md`
4. `docs/HANDOFF_BELLINI_GWN_AG60_P0.md`
5. `docs/P0_RUNTIME_RECOVERY_MANIFEST.json`
6. PR #110 and draft PR #111.

## Required checkpoint before changing agent/provider

Persist:

- objective and next single action;
- `PROVEN`, `CLAIMED`, or `UNKNOWN` classification;
- branch, SHA, PR, worktree, and dirty-tree status;
- commands/tests executed and exact outputs;
- services changed and rollback procedure;
- Temporal workflow/run IDs and heartbeats;
- evidence paths and hashes;
- unresolved blockers and required human action.

Never claim that a dispatched message equals execution. A task is active only with a real worker/run/heartbeat.

## Prompt for Antigravity — platform implementation

```text
Read docs/CANONICAL_CONTINUITY_HANDOFF_20260930.md first, then the four referenced recovery/handoff files. Do not depend on chat history. Work local-first and preserve evidence.

P0 objectives:
1. Audit MCP Full read-only as an internal backend and publish a PASS/FAIL matrix without exposing secrets.
2. Prove or disprove Intel/AMD coordination with the dual-node acceptance canaries in the handoff.
3. Repair live deployment drift for create_ops_task(source_message_id, conversation_ref, related_project) and route_tools(for_model), then prove the real Small runtime uses the corrected signatures.
4. Make the strict public OAuth audit pass, including the canonical WWW-Authenticate challenge.
5. Design/implement the governed Capability Gateway search/describe/invoke/execution contract without increasing MCP Small beyond 25 direct tools. Replace domain-specific direct tools only after parity tests.
6. Do not merge PR #111 until its gates are green. Do not use interactive login loops. Do not mutate Bellini; its review remains read-only.
7. Before stopping, update this handoff with branch, SHA, tests, runtime evidence, rollback, blockers, and the next action.
```

## Prompt for Cursor or Codex — resume engineering

```text
Read docs/CANONICAL_CONTINUITY_HANDOFF_20260930.md and the linked Notion handoff. Inspect Git state and live runtime before writing. Continue from the first FAIL or UNKNOWN gate. Do not add domain-specific tools to MCP Small; use the governed capability architecture. Do not mark tasks complete directly in Mongo. Preserve changes in an isolated branch/worktree, run bounded tests, and update the handoff before exit.
```

## Prompt for the Bellini review chat

```text
Continue the Bellini I-II review in read-only mode. Do not request new public MCP Small tools. Express every missing operation as an internal capability requirement, preferably network.device.query.v1 with parameterized sections. Use existing Device Fabric tools where sufficient. Return the capability contract, required evidence, and any blocker; do not perform mutations or broaden scope beyond Bellini I-II.
```

## Local checkout continuation

After this documentation PR is merged, each authorized local checkout should fetch/pull the canonical branch and verify a clean tree before work. If a production runtime cannot be traced to an approved SHA, capture hashes and treat it as drift; do not overwrite it blindly. Runtime-only modules listed in `docs/P0_RUNTIME_RECOVERY_MANIFEST.json` require preservation and independent canary before convergence.
