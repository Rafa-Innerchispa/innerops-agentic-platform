# All Things Agentic Hackathon 2026

## Final submission scope

**Project:** InnerOS — The Self-Healing Agentic Operating System  
**Category:** Fortified Enterprise Fleet  
**Final hackathon snapshot:** August 31, 2026  
**Canonical Judge Console:** https://inneros.creatorcore.ai/app/judge  
**Canonical repository:** https://github.com/Rafa-Innerchispa/innerops-agentic-platform  
**Frozen branch:** `hackathon-freeze-20260831`

InnerOS / ARIA is the unified enterprise agent operating layer built and substantially developed during the hackathon submission period. It coordinates persistent agent state, routing, execution, verification, recovery, evidence, and local/cloud compute behind bounded policy.

## Mandatory Google requirements

InnerOS satisfies the mandatory hackathon requirements through verified paths:

- **Gemini 3.5+** through the Google Gemini / Vertex path.
- **Google Agent Development Kit (ADK)** and **Google GenAI SDK (`google-genai`)**.
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
- Explicit `PASS / PARTIAL / FAIL / DEGRADED` truth states.

## Google evidence

Verified hackathon evidence includes:

- Gemini 3.5+ invocation.
- Cloud Run deployment in project `innerops-agentic-platform`.
- Firestore write and verification.
- Pub/Sub publish evidence.
- ADK / Google GenAI integration path.
- Google Cloud logging / observability evidence.
- Model Armor benign-path verification and guarded hostile-input handling.
- FunctionGemma integration through Vertex AI / Model Garden.

## Additional Google model bonus — FunctionGemma

FunctionGemma was successfully deployed and proven on Vertex AI / Model Garden during the hackathon and was intentionally undeployed after an earlier proof window to avoid idle GPU cost.

For the final submission window, the FunctionGemma route was reconnected and the Judge Test 3 path was updated to use fresh Vertex endpoint discovery rather than a stale dedicated DNS value.

The final production hotfix also corrected the Judge API so a truthful `PARTIAL` FunctionGemma result is returned as evidence instead of being incorrectly converted into an HTTP 502 error.

**Final truth rule:** FunctionGemma is probed live when available. The Judge Console may report `PASS`, `PARTIAL`, or `FAIL` based on the real Vertex response. No synthetic PASS is allowed.

The final Judge integration hotfix is preserved at:

`Rafa-Innerchispa/innerspark-workforce-ai@6808383d9f098839e5754a8405e010dd9bd28601`

The canonical hackathon runtime and Google integration remain in this repository; the integration commit above is deployment evidence for the live Judge UI hosted inside the existing application shell.

## Judge workflow

1. Log in at https://inneros.creatorcore.ai/app/login?judge=1 using the credentials in `JUDGES_START_HERE.md`.
2. Open https://inneros.creatorcore.ai/app/judge.
3. Run any Judge test individually.
4. Confirm a fresh `correlation_id` and truthful terminal state.
5. Inspect the same execution in Global Live Trace.
6. Use ARIA for natural-language interaction and test explanations.
7. Inspect provider / model / runtime provenance.
8. For the Gemini artifact proof, open or download the generated PDF.

A PASS should only be presented when matching execution evidence exists. Historical, degraded, unavailable, or dry-run states are labeled explicitly rather than promoted to live success.

## Seven final judge proofs

The frozen Judge experience is organized around seven independently runnable proofs:

1. system health and fresh correlation ID;
2. A2A discovery / agent connectivity;
3. live FunctionGemma / Vertex AI probe;
4. Gemini generation with downloadable PDF evidence;
5. ARIA arbitrary natural-language challenge;
6. local-first AMD model inference;
7. bounded multi-agent dispatch with durable trace evidence.

## Reproducibility

Start with [`../JUDGES_START_HERE.md`](../JUDGES_START_HERE.md) and the root [`../README.md`](../README.md).

For the exact submitted source snapshot:

```bash
git clone https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git
cd innerops-agentic-platform
git checkout hackathon-freeze-20260831
```

The repository includes environment creation, core API and MCP startup, verification commands, and bounded regression testing.

## Pre-existing work disclosure

Before the hackathon, the ecosystem already contained real products, local AI infrastructure, MCP integrations, server services, and earlier agent experiments.

The hackathon contribution is the new unified InnerOS / ARIA enterprise fleet layer, including durable coordination, expanded A2A interoperability, Google-native execution, Resource Fabric routing, Judge Console / Live Trace, bounded self-healing, persistent evidence, governance, and improved coordination truth across agent execution planes.

## Final demo principle

InnerOS notices what matters, chooses the right bounded intelligence and execution resource, does what it safely can, proves what happened, and brings the human back only when the human is actually needed.
