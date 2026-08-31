# Judges: Start Here

**Project:** InnerOS — The Self-Healing Agentic Operating System  
**Track:** All Things Agentic Hackathon 2026 — Fortified Enterprise Fleet  
**Canonical source repository:** this repository  
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

## One-repository rule

This repository is the canonical hackathon source of truth.

InnerOS operates real existing products and infrastructure, so the live Judge Console is hosted inside an existing application shell. Those products are integration targets and evidence sources, not additional repositories a judge needs to inspect to understand the hackathon project.

The hackathon-specific orchestration, agent runtime, A2A/MCP control plane, Gemini/Google integration, local/cloud resource routing, policy, observability, recovery and verification code are maintained here.

## What to evaluate

InnerOS is not a collection of chatbot personas. It is an operational agent fleet built around a durable loop:

```text
signal -> relevance -> memory -> decision -> delegation
       -> execution -> verification -> recovery -> evidence -> learning
```

The demo is designed to prove seven things individually:

1. A judge action can be dispatched independently with a fresh correlation ID.
2. ARIA can route work to a real model/runtime rather than a canned response.
3. A2A/MCP execution produces durable task state and evidence.
4. The Global Live Trace exposes the execution chain without fabricating events.
5. Local sovereign compute and Gemini/Google Cloud can participate behind the same capability contract.
6. Historical infrastructure evidence is presented truthfully: FunctionGemma is proven historically but is not claimed as currently serving; the DigitalOcean MI325X burst was proven and intentionally destroyed to avoid idle cost.
7. Stalled or failed work is observable and recoverable instead of being silently presented as success.

## Repository map

- `platform/inneros_core_runtime/` — canonical InnerOS runtime and tool/control plane.
- `platform/inneros_core_runtime/a2a_*` — A2A registry, bridge, controller and durable task handling.
- `platform/inneros_core_runtime/gemini_runtime.py` — Gemini runtime integration.
- `platform/inneros_core_runtime/google_adk_a2a.py` — Google ADK/A2A integration path.
- `platform/inneros_core_runtime/resource_fabric.py` — capability/cost-aware local-first routing.
- `platform/inneros_core_runtime/external_repair_agent.py` — bounded external coding-agent escalation.
- `platform/inneros_core_runtime/dev_swarm_scheduler.py` — local multi-agent development scheduler.
- `platform/inneros_core_runtime/work_liveness.py` — work-liveness guard.
- `platform/inneros_core_runtime/integration_guardian.py` — verification/acceptance gate.
- `platform/inneros_core_runtime/racb_locks.py` — repository/action coordination locks.
- `docs/ALL_THINGS_AGENTIC.md` — hackathon requirements and evidence mapping.
- `docs/` — architecture, security, story, Google/hackathon evidence and operating notes.

## Fast local reproduction

```bash
git clone https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git
cd innerops-agentic-platform/platform
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
3. Run one Judge action at a time.
4. Observe the fresh correlation ID and execution state.
5. Send a natural-language request through ARIA and inspect provider/model/runtime provenance.
6. Watch the Global Live Trace for dispatch, acknowledgement, running state and terminal evidence.
7. Use the Google/Gemini path for cloud proof and the local routes for sovereign-compute proof.
8. Treat any explicit `ERROR`, `TIMEOUT`, `DEGRADED`, `PARTIAL`, or historical/not-running label as a truthful system state, not a hidden success.

## Google technology

The hackathon path uses or demonstrates:

- Gemini 3.5+
- Google Agent Development Kit (ADK)
- Google GenAI SDK (`google-genai`)
- Google Cloud Run
- Firestore
- Pub/Sub
- Google Cloud IAM / bounded agent identity patterns
- Model Armor / agentic-defense controls where integrated

See [`docs/ALL_THINGS_AGENTIC.md`](docs/ALL_THINGS_AGENTIC.md) and the main `README.md` for architecture and evidence details.

## Pre-existing work disclosure

Before the submission period, the ecosystem already contained real products, local AI infrastructure, MCP integrations and earlier agent experiments. The hackathon contribution is the unified InnerOS/ARIA enterprise operating layer, durable execution semantics, local/cloud resource fabric, recovery/verification behavior, Google integration path, security/governance hardening and coherent judge/demo experience built during the submission period.

## Evaluation principle

**Do not judge InnerOS by how many agents are listed. Judge it by whether work can be routed, executed, verified, recovered and evidenced without requiring a human to babysit every step.**
