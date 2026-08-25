# InnerOS Recovery and Continuity

This file is the first durable recovery document for a new ChatGPT/agent session.

## Recovery order
1. Read this file and `docs/PRODUCT_STATUS.md`.
2. Read `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/AGENT_OPERATING_RULES.md` and `docs/SUBMISSION_CHECKLIST.md`.
3. Read MCP live coordination (`get_coordination_live`) and acknowledge its current revision.
4. Read the latest `chatgpt/handoff/*` checkpoint for execution detail that has not yet become a durable commit.
5. Fetch the relevant GitHub branches/SHAs. Never assume `main` is canonical.
6. Inspect task worktree and tests before writing.
7. Continue execution; do not merely restate status if local capacity is available.

## Canonical branches as of 2026-08-25
### InnerOS
- Repo: `Rafa-Innerchispa/innerops-agentic-platform`
- Base: `local-agent/chatgpt-inneros-integration-20260824`
- Base SHA: `fd59a17c91a8ba311f2a4668ac4e2bcf794795a9`
- Product entrypoint: `src/server.js`

### Workforce
- Repo: `Rafa-Innerchispa/innerspark-workforce-ai`
- Base: `local-agent/chatgpt-workforce-real-auth-20260824`
- Verified canonical commit: `cd50064` or descendant.
- Previously verified tests at that commit: 7 suites, 30/30 PASS. Build/lint were not verified and must not be claimed.

### Payroll AI
- Repo: `Rafa-Innerchispa/innerspark-payroll-ai`
- Product foundation branch: `local-agent/payroll-product-foundation-20260824`.
- Advanced Ecuador payroll remains separate from Workforce basic pre-payroll.

## Active critical work
- `ops_d8869e29596b`: Productivity/ROI v3 on canonical InnerOS base. Must implement real telemetry/schema/sessionization/KPI/backfill/DB37/API/dashboard/tests. Do not accept scaffold/status-only output.
- `ops_8cfb9b6b1f1a`: Workforce schedule-backed novelty logic. Current blocker: `tests/noveltyProcessor.test.ts` imports missing `../src/lib/employeeService`. Repair on canonical Workforce branch and rerun Jest.
- `ops_ab51ffea64a5`: Dev Swarm false-PASS + idle-P0 regression repair. External Codex path was spend-gated; do not approve external spend automatically.
- `ops_c3e662992fd6`: durable continuity protocol and repository documentation.
- `ops_be4587bd9090`: module registry/tenant entitlements historical real files, but not yet proven integrated.
- `ops_bfa2aaaa0d51`: PC Doctor SalesOps Founder OS historical slice, but not yet proven integrated.

## Known false completion evidence
Do not treat these historical tasks as product completion:
- `ops_f3f88ac0585d`
- `ops_348edbc5fedf`
They were reported PASS after primarily producing `package.json`, `src/dev_swarm_frontend_status.js` and `tests/scaffold.test.mjs`.

## Local AI evidence
AMD `.5` Qwen3 Coder was freshly verified through vLLM/ROCm. Preferred model: `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ` (`qwen3-coder-30b-awq`). Intel `.4` is test/execution/fallback.

## Session checkpoint contract
Whenever a material change occurs, persist these fields before context is lost:
- date/time and objective
- repo and canonical base branch/SHA
- work branch/worktree
- ops task + correlation id
- substantive files changed
- tests executed and exact PASS/FAIL state
- blocker/root cause
- decisions made and rationale
- new ideas worth preserving
- claims that are explicitly NOT yet valid
- next executable actions in priority order
- commit/push/deploy state

A chat handoff is a live pointer. Important architecture, decisions, recovery instructions and submission facts must also be promoted into repository docs.

## Recovery success test
A fresh agent with no previous conversation history passes continuity recovery only if it can answer from GitHub + MCP:
- What is InnerOS and what is the hackathon product?
- Which branches are canonical and why?
- What is complete, partial, blocked or unverified?
- What are the active P0 tasks and exact next actions?
- Which claims are prohibited without new evidence?
- What should execute next using local resources?
