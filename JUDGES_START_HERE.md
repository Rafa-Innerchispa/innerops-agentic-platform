# Judges: Start Here

**Project:** InnerOS — The Self-Healing Agentic Operating System  
**Track:** All Things Agentic Hackathon 2026 — Fortified Enterprise Fleet  
**Final hackathon snapshot:** August 31, 2026  
**Canonical source repository:** this repository  
**Frozen branch:** `hackathon-freeze-20260831`  
**Live Judge Console:** https://inneros.creatorcore.ai/app/judge  
**Devpost:** https://devpost.com/software/innerops-aria-enterprise-agent-fleet

## Demo access

Open:

https://inneros.creatorcore.ai/app/login?judge=1

Use either demo username:

- `HACKATHON-JUDGE`
- `DEVPOST-JUDGE`

Password:

- `demo123`

After login, open the Judge Console and run the tests individually.

## Final submission state

This document describes the **frozen hackathon version**, not later product development.

At the submission freeze:

- the production Judge Console was deployed and running;
- ARIA and the Global Live Trace were presented side by side for judge inspection;
- the seven judge proofs were independently runnable;
- terminal states were explicitly represented as `PASS`, `PARTIAL`, or `FAIL`;
- Gemini / Google Cloud proof, local-model proof, A2A coordination, downloadable artifact generation, and live trace evidence were exposed through the Judge Console;
- FunctionGemma was reconnected to the live Vertex AI path for the final submission window;
- the final FunctionGemma hotfix removed reliance on a stale dedicated Vertex DNS value and prevented a truthful `PARTIAL` probe from being incorrectly surfaced as an HTTP 502 failure.

FunctionGemma remains subject to real endpoint availability and cost controls. The Judge Console must never manufacture a `PASS`: if the live Vertex route is unavailable, it reports the real degraded state.

## Source-of-truth and integration note

This repository is the canonical hackathon source for the InnerOS / ARIA operating layer, Google integration, A2A/MCP control plane, Resource Fabric, policy, recovery, observability, and reproducibility material.

The live Judge UI is hosted inside an existing operational application shell because InnerOS operates real products rather than a disposable demo. The final Judge production hotfix is preserved in the integration repository at commit:

`Rafa-Innerchispa/innerspark-workforce-ai@6808383d9f098839e5754a8405e010dd9bd28601`

That integration commit is referenced as deployment evidence; judges do not need to treat Workforce as the hackathon project itself.

## What to evaluate

InnerOS is not a collection of chatbot personas. It is an operational agent fleet built around a durable loop:

```text
signal -> relevance -> memory -> decision -> delegation
       -> execution -> verification -> recovery -> evidence -> learning
```

The demo is designed to prove seven things individually:

1. A judge action can be dispatched independently with a fresh correlation ID.
2. A2A agent discovery and connection evidence are visible.
3. FunctionGemma / Vertex AI can be probed truthfully as a live Google model route.
4. Gemini can produce a real downloadable PDF artifact with provider/model provenance.
5. ARIA can accept a natural-language challenge and route it through the operating layer.
6. A sovereign local model can execute on the local AMD AI infrastructure.
7. Bounded multi-agent execution can be traced through durable state and Global Live Trace evidence.

The key evaluation principle is simple: a visible `PASS` must correspond to real execution evidence. Historical, degraded, unavailable, or dry-run states are labeled as such.

## Repository map

- `platform/inneros_core_runtime/` — canonical InnerOS runtime and tool/control plane.
- `platform/inneros_core_runtime/a2a_*` — A2A registry, bridge, controller and durable task handling.
- `platform/inneros_core_runtime/gemini_runtime.py` — Gemini runtime integration.
- `platform/inneros_core_runtime/google_adk_a2a.py` — Google ADK/A2A integration path.
- `platform/inneros_core_runtime/google_extra_models.py` — additional Google model routes, including FunctionGemma integration support.
- `platform/inneros_core_runtime/resource_fabric.py` — capability/cost-aware local-first routing.
- `platform/inneros_core_runtime/external_repair_agent.py` — bounded external coding-agent escalation.
- `platform/inneros_core_runtime/dev_swarm_scheduler.py` — local multi-agent development scheduler.
- `platform/inneros_core_runtime/work_liveness.py` — work-liveness guard.
- `platform/inneros_core_runtime/integration_guardian.py` — verification/acceptance gate.
- `platform/inneros_core_runtime/racb_locks.py` — repository/action coordination locks.
- `docs/ALL_THINGS_AGENTIC.md` — hackathon requirements and final evidence mapping.
- `docs/` — architecture, security, story, Google/hackathon evidence and operating notes.

## Fast local reproduction

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

Core API default:

```text
http://127.0.0.1:8101
```

Optional MCP surface:

```bash
./run_mcp.sh
```

MCP default:

```text
http://127.0.0.1:8102
```

Run the bounded regression suite from the repository root:

```bash
python3 -m unittest discover -s platform/tests -p 'test_*.py'
```

Provider credentials are optional unless the corresponding provider path is being exercised. Secrets are intentionally not committed.

## Live demo path

1. Log in with the Judge credentials above.
2. Open https://inneros.creatorcore.ai/app/judge.
3. Run one Judge test at a time.
4. Observe the fresh correlation ID and terminal state.
5. Inspect ARIA and the Global Live Trace side by side.
6. Use the FunctionGemma / Gemini paths for Google proof and the local route for sovereign-compute proof.
7. Open or download the generated PDF artifact in the Gemini proof.
8. Treat any explicit `ERROR`, `TIMEOUT`, `DEGRADED`, `PARTIAL`, or historical label as a truthful system state, not a hidden success.

## Google technology

The hackathon path uses and demonstrates:

- Gemini 3.5+
- Google Agent Development Kit (ADK)
- Google GenAI SDK (`google-genai`)
- Vertex AI
- FunctionGemma / Gemma integration
- Google Cloud Run
- Firestore
- Pub/Sub
- Google Cloud IAM / bounded agent identity patterns
- Model Armor / agentic-defense controls where integrated

See [`docs/ALL_THINGS_AGENTIC.md`](docs/ALL_THINGS_AGENTIC.md) and the main `README.md` for architecture and evidence details.

## Pre-existing work disclosure

Before the submission period, the ecosystem already contained real products, local AI infrastructure, MCP integrations and earlier agent experiments. The hackathon contribution is the unified InnerOS/ARIA enterprise operating layer, durable execution semantics, local/cloud Resource Fabric, expanded A2A interoperability, Google-native execution paths, Judge Console / Live Trace, recovery and verification behavior, security/governance hardening, and the coherent judge/demo experience built during the submission period.

## Evaluation principle

**Do not judge InnerOS by how many agents are listed. Judge it by whether work can be routed, executed, verified, recovered and evidenced without requiring a human to babysit every step.**
