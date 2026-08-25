# Agent Operating Rules

## 1. Recover before modifying
Read `docs/RECOVERY.md`, `docs/PRODUCT_STATUS.md`, live MCP coordination and the latest handoff. Resolve the canonical base ref/SHA. Inspect existing product files before creating a framework or module.

## 2. Local-first
Use local AMD `.5`/Qwen3 Coder as preferred heavy coding path. Use Intel `.4` for execution/tests/fallback. External coding agents are escalation only and external spend requires explicit owner approval.

## 3. Worktree isolation
Never develop directly on a protected/canonical branch. Use an isolated work branch/worktree from the recorded canonical base. Respect locks and idempotency.

## 4. Evidence-aware completion
For every task record:
- requested base and resolved SHA
- substantive product files changed
- tests and exact results
- selected node/model when AI generation is involved
- commit SHA
- blockers/missing requirements

Status/scaffold/probe/contract/package-only files do not satisfy product implementation unless explicitly required.

## 5. No silent fallback
If a required local model/node/framework is unavailable, record the failure and route deliberately. Never silently replace required hackathon technology or claimed runtime with another provider.

## 6. Tenant/security rules
Authorization and module entitlements are server-side. Never expose cross-tenant company lists to ordinary tenant users. Never store secrets in client code, repo docs or task evidence. Sensitive/irreversible actions use explicit approval gates.

## 7. Preserve decisions and ideas
When a conversation introduces a material architectural decision, new product idea, risk or future improvement, persist it in `docs/DECISIONS.md`, the relevant product doc/backlog, or a formal ops task. Do not wait for chat context to fill.

## 8. Continuity checkpoint
Before ending a significant development phase or when context risk rises, create/update a handoff containing branch/SHA/task/files/tests/blockers/decisions/ideas/next actions and promote durable facts into repository docs.

## 9. Git documentation hygiene
Automated status sync must not commit merely because a timestamp changed. Prefer semantic diffs, meaningful milestones or bounded checkpoints. Do not drown product history in heartbeat commits.

## 10. Hackathon-first prioritization
Until the All Things Agentic submission is safe, prioritize work in this order:
1. mandatory competition technology and rule compliance;
2. autonomous end-to-end workflow that proves operational utility;
3. architecture/state/security/failure evidence;
4. reproducible repo + tests + Google Cloud proof;
5. demo/video/diagram/submission completeness;
6. non-critical polish and optional bonus integrations.

A task that does not improve a mandatory requirement or judging criterion should not displace a P0 that does.
