# InnerOS Architecture

## Purpose
InnerOS is the durable operating shell for InnerChispa/PC Doctor agentic products. It composes existing products and operational primitives instead of rebuilding them as isolated demos.

## Canonical product base
- Repository: `Rafa-Innerchispa/innerops-agentic-platform`
- Canonical integration base: `local-agent/chatgpt-inneros-integration-20260824`
- Verified base SHA on 2026-08-25: `fd59a17c91a8ba311f2a4668ac4e2bcf794795a9`
- `main` is not a valid product base for current lanes; it has historically been incomplete/minimal.
- Existing shell entrypoint: `src/server.js`.

## Product flow
1. User authenticates with username/password or Google Auth.
2. Server resolves identity and tenant.
3. Server returns tenant-authorized module catalog.
4. User selects a module inside the common InnerOS AppShell.
5. Every API/action remains tenant-scoped and audit-capable.

Tenant entitlements are server-side. Do not use `localStorage`, client-controlled environment values, or UI-only checks as authorization.

PC Doctor is the canonical owner tenant and may receive every owner-approved module. Other tenants receive only explicit entitlements.

## Current module map
- Overview: platform posture and operational summary.
- Workforce: people, attendance, schedules, biometric mappings. Product source remains `Rafa-Innerchispa/innerspark-workforce-ai`.
- Payroll: separate advanced Ecuador payroll product in `Rafa-Innerchispa/innerspark-payroll-ai`; Workforce contains only basic pre-payroll impacts.
- Access / Visitors / Credentials / Devices: reusable building and VigilOS capabilities through normalized tenant-scoped events.
- ARIA: agent runtime, scoped tools, memory, alerts, approvals and workflows.
- Workflows: resumable/idempotent orchestration.
- Approvals: human gates for sensitive actions.
- Audit: trace state-changing agent and operator actions.
- Productivity & ROI: evidence-backed human/agent productivity, savings, cost avoidance and capacity metrics.
- PC Doctor SalesOps Founder OS: client/prospect -> need -> QuoteOps -> approval -> job/project -> evidence/report -> billing/history.

## Runtime posture
Development is local-first.
- AMD `.5`: primary heavy coding/inference node, Radeon AI PRO R9700, local vLLM/ROCm.
- Preferred coding model: `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ`, alias `qwen3-coder-30b-awq`.
- Intel `.4`: execution, tests and fallback; RTX 3060 12 GB.
- External agents/models are repair/escalation only when local capability is genuinely blocked. External spend requires explicit approval.

## Google / hackathon architecture
For All Things Agentic, the submission architecture must visibly include the required Google components:
- Gemini 3.5 or newer via Gemini API or Vertex AI.
- At least one Google agent framework: ADK, Google GenAI SDK, Antigravity SDK or GenKit.
- At least one Google Cloud service such as Cloud Run or Firestore.

The intended competition positioning is **Fortified Enterprise Fleet** because InnerOS already maps naturally to registry/lifecycle, long-running runtime and memory, identity/gateway/governance, tenant isolation, audit/observability and cross-module operations.

## State and knowledge layers
### Durable project truth
GitHub repository documentation and commits are the versioned source for architecture, product state, decisions, recovery, submission requirements and reproducibility.

### Live execution truth
MCP/Mongo provides `ops_tasks`, state transitions, heartbeats, workers, worktrees, blockers, agent messages and current coordination state.

Neither layer replaces the other. A new session should use GitHub for durable intent/history and MCP for the latest execution state.

## Completion rule
A module is not complete because a worker emitted `PASS`. Completion requires evidence matching the task: substantive product files, required capabilities/routes, deterministic tests, commit SHA and architecture fit. Scaffold/status/probe/package-only changes do not count as product implementation.
