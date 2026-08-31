# All Things Agentic Hackathon 2026

## Final submission scope

**Project:** InnerOS — The Self-Healing Agentic Operating System  
**Category:** Fortified Enterprise Fleet  
**Frozen branch:** `hackathon-freeze-20260831`  
**Judge Console:** https://inneros.creatorcore.ai/app/judge

InnerOS / ARIA is the unified enterprise agent operating layer completed for the hackathon submission. It coordinates persistent state, routing, execution, verification, recovery, evidence, and local/cloud compute behind bounded policy.

## Mandatory Google requirements — satisfied

InnerOS satisfies the required Google technology paths:

- **Gemini 3.5+** through the Google Gemini / Vertex path.
- **Google Agent Development Kit (ADK)**.
- **Google GenAI SDK (`google-genai`)**.
- **Google Cloud infrastructure:** Cloud Run, Firestore, and Pub/Sub.

## Fortified Enterprise Fleet mapping

### Discovery & Lifecycle

- Canonical agent registry and capability catalog.
- A2A Agent Cards for approved agents.
- Durable task lifecycle state.

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
- Model Armor / agentic-defense controls where integrated.

### Telemetry

- Global Live Trace.
- Persisted execution evidence.
- Provider, model, runtime, node, correlation and status provenance.
- Explicit `PASS / PARTIAL / FAIL` terminal truth states.

## Verified Google evidence

The final submission includes verified evidence for:

- Gemini 3.5+ invocation;
- Cloud Run deployment in project `innerops-agentic-platform`;
- Firestore persistence;
- Pub/Sub event publication;
- ADK / Google GenAI integration;
- Google Cloud observability;
- Model Armor / guarded-input path where integrated;
- FunctionGemma integration through Vertex AI / Model Garden.

## FunctionGemma / Vertex AI

FunctionGemma is included as the additional Google model integration.

For the final submission, Judge Test 3 was reconnected to the live Vertex path and successfully exercised after the final hotfix. The hotfix removed reliance on stale dedicated Vertex DNS, uses current endpoint discovery, and prevents an application-level HTTP 502 from masking a truthful model probe result.

The final Judge integration hotfix is preserved at:

`Rafa-Innerchispa/innerspark-workforce-ai@6808383d9f098839e5754a8405e010dd9bd28601`

## Seven final judge proofs

1. system health and fresh correlation ID;
2. A2A discovery / agent connectivity;
3. live FunctionGemma / Vertex AI execution;
4. Gemini generation with downloadable PDF evidence;
5. ARIA natural-language challenge;
6. local-first AMD model inference;
7. bounded multi-agent dispatch with durable trace evidence.

## Judge workflow

1. Log in at https://inneros.creatorcore.ai/app/login?judge=1 using the credentials in `JUDGES_START_HERE.md`.
2. Open the Judge Console.
3. Run any test individually.
4. Confirm the fresh `correlation_id` and terminal state.
5. Inspect the same execution in Global Live Trace.
6. Inspect provider / model / runtime provenance.
7. Open or download the Gemini PDF artifact.

## Reproducibility

Start with [`../JUDGES_START_HERE.md`](../JUDGES_START_HERE.md) and [`../README.md`](../README.md).

```bash
git clone https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git
cd innerops-agentic-platform
git checkout hackathon-freeze-20260831
```

The repository includes environment creation, core API and MCP startup, verification commands, and regression testing.

## Pre-existing work disclosure

The broader ecosystem already contained real products and infrastructure before the hackathon. The hackathon contribution is the unified InnerOS / ARIA enterprise fleet layer and the substantial submission-period work: durable coordination, expanded A2A interoperability, Google-native execution, Resource Fabric routing, Judge Console / Global Live Trace, bounded self-healing, persistent evidence, governance, and consistent execution truth across agent planes.

## Final principle

InnerOS notices what matters, chooses the right bounded intelligence and execution resource, does what it safely can, proves what happened, and brings the human back only when human authority is actually needed.
