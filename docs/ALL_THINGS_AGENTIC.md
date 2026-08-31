# All Things Agentic Hackathon 2026

## Submission scope

**Project:** InnerOS — The Self-Healing Agentic Operating System  
**Category:** Fortified Enterprise Fleet  
**Canonical Judge Console:** https://inneros.creatorcore.ai/app/judge  
**Canonical repository:** https://github.com/Rafa-Innerchispa/innerops-agentic-platform

InnerOS / ARIA is the unified enterprise agent operating layer built and substantially developed during the hackathon submission period. It coordinates persistent agent state, routing, execution, verification, recovery, evidence, and local/cloud compute behind bounded policy.

## Mandatory Google requirements

InnerOS satisfies the mandatory hackathon requirements through the following verified paths:

- **Gemini 3.5+** through the Google Gemini / Vertex path.
- **Google Agent Development Kit (ADK)** and **Google GenAI SDK (google-genai)**.
- **Google Cloud infrastructure:** Cloud Run, Firestore, and Pub/Sub.

## Fortified Enterprise Fleet mapping

### Discovery & Lifecycle

- Canonical agent registry and capability catalog.
- A2A Agent Cards for approved agents.
- Durable task lifecycle state rather than treating inbox delivery as execution.

### Core Execution & State

- Durable `ops_task` lifecycle.
- Correlation IDs.
- Ownership / revision checks.
- Heartbeats and bounded recovery.
- Persistent operational context and memory.

### Security & Governance

- Scoped and allowlisted tools.
- Repository locks and isolated worktrees.
- Server-side secret handling.
- Approval gates for high-impact actions.
- Identity / policy boundaries.
- Model Armor / agentic-defense evidence on the Google path where applicable.

### Telemetry

- Global Live Trace.
- Persisted execution evidence.
- Provider, model, runtime, node, correlation and status provenance where available.
- Explicit PASS / PARTIAL / FAIL / DEGRADED truth states.

## Google evidence

Verified hackathon evidence includes:

- Gemini 3.5+ invocation.
- Cloud Run deployment in project `innerops-agentic-platform`.
- Firestore write and verification.
- Pub/Sub publish evidence.
- ADK / Google GenAI integration path.
- Google Cloud logging / observability evidence.
- Model Armor benign-path verification and guarded hostile-input handling.

## Additional Google model bonus

**FunctionGemma** was successfully deployed and proven on Vertex AI / Model Garden during the hackathon. It was later intentionally undeployed to eliminate idle GPU cost.

Truthful state:

`HISTORICAL PROVEN / CURRENTLY NOT_RUNNING / READY_TO_REDEPLOY`

This is cost governance, not a simulated integration.

## Judge workflow

1. Open https://inneros.creatorcore.ai/app/judge.
2. Run any Judge test individually.
3. Confirm a fresh `correlation_id`.
4. Inspect the same execution in Global Live Trace.
5. Use ARIA for natural-language interaction and test explanations.
6. Inspect provider / model / runtime provenance and truthful terminal state.

A PASS should only be presented when matching persisted evidence exists. Historical or currently unavailable integrations are labeled explicitly rather than promoted to live success.

## Reproducibility

Start with [`../JUDGES_START_HERE.md`](../JUDGES_START_HERE.md) and the root [`../README.md`](../README.md).

The repository includes clone/setup instructions, environment creation, core API and MCP startup, verification commands, and bounded regression testing.

## Pre-existing work disclosure

Before the hackathon, the ecosystem already contained real products, local AI infrastructure, MCP integrations, server services, and earlier agent experiments.

The hackathon contribution is the new unified InnerOS / ARIA enterprise fleet layer, including durable coordination, expanded A2A interoperability, Google-native execution, Resource Fabric routing, Judge Console / Live Trace, bounded self-healing, persistent evidence, governance, and improved coordination truth across agent execution planes.

## Demo principle

InnerOS notices what matters, chooses the right bounded intelligence and execution resource, does what it safely can, proves what happened, and brings the human back only when the human is actually needed.
