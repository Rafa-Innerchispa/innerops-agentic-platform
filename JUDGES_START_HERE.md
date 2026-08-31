# Judges: Start Here

**Project:** InnerOS — The Self-Healing Agentic Operating System  
**Track:** All Things Agentic Hackathon 2026 — Fortified Enterprise Fleet  
**Final hackathon snapshot:** August 31, 2026  
**Frozen branch:** `hackathon-freeze-20260831`  
**Live Judge Console:** https://inneros.creatorcore.ai/app/judge  
**Devpost:** https://devpost.com/software/innerops-aria-enterprise-agent-fleet

## Demo access

Open: https://inneros.creatorcore.ai/app/login?judge=1

- Username: `HACKATHON-JUDGE` or `DEVPOST-JUDGE`
- Password: `demo123`

After login, open the Judge Console and run the tests individually.

## Final submission state

The frozen submission is the completed hackathon build.

The final Judge experience includes:

- ARIA and Global Live Trace visible together;
- seven independently runnable judge proofs;
- fresh correlation IDs and execution evidence;
- explicit `PASS / PARTIAL / FAIL` terminal truth states;
- Gemini 3.5+ execution;
- Google ADK and Google GenAI SDK integration;
- Cloud Run, Firestore and Pub/Sub evidence;
- live Vertex AI / FunctionGemma Judge Test 3 path;
- Gemini PDF generation with open/download artifact evidence;
- A2A agent discovery and bounded multi-agent execution;
- sovereign local AMD model inference through the local-first Resource Fabric.

The final FunctionGemma production hotfix removed the stale Vertex DNS dependency, uses fresh endpoint discovery and prevents a truthful degraded result from being misreported as an HTTP 502 application failure. The final live Judge Test 3 path was successfully exercised after the hotfix.

## What to evaluate

InnerOS is an operational agent fleet built around a durable loop:

```text
signal -> relevance -> memory -> decision -> delegation
       -> execution -> verification -> recovery -> evidence -> learning
```

The seven judge proofs demonstrate:

1. system health and a fresh correlation ID;
2. A2A agent discovery and connectivity;
3. live FunctionGemma / Vertex AI execution;
4. Gemini generation with a real downloadable PDF artifact;
5. ARIA natural-language interaction;
6. sovereign local AMD model inference;
7. bounded multi-agent dispatch with durable Global Live Trace evidence.

A visible `PASS` corresponds to real execution evidence. The interface does not manufacture successful states.

## Google technology used

- Gemini 3.5+
- Google Agent Development Kit (ADK)
- Google GenAI SDK (`google-genai`)
- Vertex AI
- FunctionGemma / Gemma
- Cloud Run
- Firestore
- Pub/Sub
- Google Cloud identity / policy patterns
- Model Armor / agentic-defense controls where integrated

## Repository map

- `platform/inneros_core_runtime/` — canonical InnerOS runtime and tool/control plane
- `platform/inneros_core_runtime/a2a_*` — A2A registry, bridge and durable task handling
- `platform/inneros_core_runtime/gemini_runtime.py` — Gemini runtime integration
- `platform/inneros_core_runtime/google_adk_a2a.py` — Google ADK / A2A integration
- `platform/inneros_core_runtime/google_extra_models.py` — additional Google model routes including FunctionGemma
- `platform/inneros_core_runtime/resource_fabric.py` — local/cloud capability routing
- `platform/inneros_core_runtime/integration_guardian.py` — verification / acceptance gate
- `docs/ALL_THINGS_AGENTIC.md` — final requirements and evidence mapping

The live Judge UI is hosted inside an existing operational application shell. Its final production integration hotfix is preserved at:

`Rafa-Innerchispa/innerspark-workforce-ai@6808383d9f098839e5754a8405e010dd9bd28601`

## Reproduce the frozen source

```bash
git clone https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git
cd innerops-agentic-platform
git checkout hackathon-freeze-20260831
cd platform
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./run.sh
```

Optional MCP surface:

```bash
./run_mcp.sh
```

Run regression tests from the repository root:

```bash
python3 -m unittest discover -s platform/tests -p 'test_*.py'
```

Secrets are intentionally not committed.

## Pre-existing work disclosure

The broader ecosystem already contained real products and infrastructure before the event. The hackathon contribution is the unified InnerOS / ARIA enterprise fleet layer and the substantial work completed during the submission period: durable coordination, expanded A2A interoperability, Google-native execution, Resource Fabric routing, Judge Console / Global Live Trace, verification and recovery behavior, persistent evidence, and governance hardening.

## Evaluation principle

**Judge InnerOS by whether work can be routed, executed, verified, recovered and evidenced without requiring a human to babysit every step.**
