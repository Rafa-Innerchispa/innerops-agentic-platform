# InnerOS Decisions and Idea Ledger

This file preserves decisions and high-value ideas that must survive chat/session boundaries. Add entries when the decision or idea becomes materially relevant; do not wait for the end of a long conversation.

## 2026-08-25 — Local-first is a permanent engineering rule
**Decision:** Prefer AMD `.5`, Intel `.4`, Dev Swarm and local models. External Codex/Cursor/Antigravity are repair/escalation paths only when local capability is blocked or insufficient. External spend is never silently approved.

**Reason:** Keep development capacity under owner control, reduce recurring credits/cost, preserve data sovereignty and prove the local agent architecture itself.

## 2026-08-25 — GitHub + MCP two-level continuity
**Decision:** GitHub/repository documentation is durable versioned project truth. MCP/Mongo/ops_tasks is live execution truth. Chat handoffs bridge the two but are not the final durable source.

**Reason:** Chat context is finite. A new agent must recover architecture, decisions, blockers and next actions without relying on an old conversation.

## 2026-08-25 — Preserve ideas as first-class artifacts
**Decision:** Significant ideas discovered during debugging or product discussion must be added here, to product backlog/docs, or to a formal ops task as soon as they affect future work.

**Reason:** Ideas frequently emerge inside unrelated conversations and are otherwise lost when chat context rolls over.

## 2026-08-25 — InnerOS canonical base is not main
**Decision:** Extend `local-agent/chatgpt-inneros-integration-20260824` at SHA `fd59a17c...` until a verified integration changes the canonical base.

**Reason:** `main` was observed as incomplete/minimal while this branch contains the real `src/server.js` shell and tests.

## 2026-08-25 — Dev Swarm PASS is evidence-gated
**Decision:** A product task cannot be considered complete from worker status alone. Scaffold/status/probe/package metadata are zero substantive completion unless explicitly requested.

**Reason:** Productivity/ROI tasks were falsely reported PASS without implementing the requested product.

## 2026-08-25 — Productivity/ROI must measure evidence, not mythology
**Decision:** Metrics use provenance `measured|inferred|manual|estimated`; human active time and agent background runtime remain distinct; agent runtime is not converted 1:1 to human savings.

**Idea:** Use the telemetry module not only as an internal dashboard but as evidence of InnerOS operational utility and cost avoidance in demos/sales, provided claims remain evidence-backed.

## 2026-08-25 — Hackathon category strategy
**Decision:** Current best-fit category is `Fortified Enterprise Fleet` because InnerOS/ARIA naturally demonstrates registry, runtime, persistent context, identity/gateway controls, governance/audit and observability.

**Idea:** The continuity system itself can become demo evidence for secure cross-session context over weeks, directly matching the category rather than being merely internal housekeeping.

## 2026-08-25 — Documentation commits should be semantic
**Decision:** Automated project-status sync should not create a Git commit solely because a timestamp changed. Commit when meaningful project state/evidence changes or at an intentional checkpoint.

**Reason:** Minute-by-minute timestamp commits pollute Git history and make substantive changes harder to audit.
