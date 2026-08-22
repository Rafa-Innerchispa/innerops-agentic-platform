# InnerOps Agentic Platform

InnerOps is an enterprise agentic operations platform being developed for the All Things Agentic hackathon.

## Product model

**InnerOps** is the platform. Business capabilities are modular:

- Workforce
- Payroll
- Access
- Credentials
- Visitors

**ARIA** is the cross-module agentic orchestration layer. ARIA is not a replacement for deterministic business rules; it coordinates agents, tools, memory, policy and human approvals across modules.

## Hackathon provenance

This repository was created specifically for the All Things Agentic hackathon. It intentionally builds on a pre-existing Workforce technical baseline rather than pretending that existing production work was created during the event.

Pre-existing source baseline:

- Repository: `Rafa-Innerchispa/innerspark-workforce-ai`
- Baseline branch: `main`
- Baseline commit: `97ac0ae688ebbb39dad3122b1fa507ae5f49e904`
- Baseline commit date: 2026-08-17
- Baseline purpose: Workforce/FEMAR application developed before this hackathon

The original XPRIZE/Workforce repository is preserved. New hackathon-specific architecture and implementation belong here and must remain auditable separately.

## Target architecture

The target is a Fortified Enterprise Fleet architecture:

1. **ARIA Orchestrator** — interprets goals, decomposes work and coordinates specialist agents.
2. **Agent Registry** — declares agent identity, role, capabilities, policy and version.
3. **Agent Runtime** — executes bounded tasks through explicit tools and contracts.
4. **Memory Bank** — separates durable organizational knowledge, task state and short-lived execution context.
5. **Identity & Gateway** — authenticates people, agents and tool calls and applies least privilege.
6. **Guardrails / Model Armor layer** — validates inputs/outputs and protects sensitive operations.
7. **Observability** — traces agent decisions, tool calls, latency, outcomes and human approvals.
8. **Business modules** — Workforce, Payroll, Access, Credentials and Visitors remain independently evolvable domains.

Google Cloud target: Cloud Run + Firestore initially, with Pub/Sub for asynchronous agent workflows where it materially improves reliability. Agent implementation should use Google ADK or the Google GenAI SDK and an eligible Gemini model according to the hackathon requirements.

## Repository policy

- Never rewrite or modify the preserved XPRIZE baseline as part of this hackathon.
- Clearly label pre-existing code and new hackathon work.
- Prefer isolated branches, reproducible tests and auditable commits.
- No production credentials or secrets in the repository.
- Sensitive or destructive agent actions require explicit policy and approval boundaries.

## Current bootstrap status

Repository bootstrap and architecture documentation are in progress. Deployment instructions will be added once the separate hackathon GCP project and first deployable service are provisioned.
