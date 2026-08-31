# InnerOS — The Self-Healing Agentic Operating System

> A local-first, self-healing enterprise agent fleet that coordinates Gemini, Google Cloud, sovereign local models, A2A agents, persistent state, bounded tools, verification and auditable evidence.

**All Things Agentic Hackathon 2026 — Fortified Enterprise Fleet**

## Final hackathon snapshot

This branch is the frozen submission used for judging:

```text
hackathon-freeze-20260831
```

**Start here:** [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md)  
**Evidence map:** [`docs/ALL_THINGS_AGENTIC.md`](docs/ALL_THINGS_AGENTIC.md)  
**Live Judge Console:** https://inneros.creatorcore.ai/app/judge  
**Judge login:** https://inneros.creatorcore.ai/app/login?judge=1  
**Devpost:** https://devpost.com/software/innerops-aria-enterprise-agent-fleet

Judge credentials:

- Username: `HACKATHON-JUDGE` or `DEVPOST-JUDGE`
- Password: `demo123`

## What InnerOS is

InnerOS / ARIA is an operational agent layer designed to reduce the human coordination burden across real software, infrastructure, cloud, documents, business workflows and autonomous agents.

Its durable operating loop is:

```text
signal -> relevance -> memory -> decision -> delegation
       -> execution -> verification -> recovery -> evidence -> learning
```

ARIA retrieves operational context, discovers the right bounded capability, applies identity and approval policy, chooses local or cloud compute, executes through scoped tools, verifies the result and persists evidence.

## Fortified Enterprise Fleet

The final system demonstrates:

- canonical agent / capability discovery;
- A2A Agent Cards and multi-agent delegation;
- durable task lifecycle state and correlation IDs;
- persistent operational context;
- scoped tools, locks, approvals and server-side secret handling;
- recovery and verification loops;
- Global Live Trace observability;
- capability-based local/cloud Resource Fabric routing;
- explicit `PASS / PARTIAL / FAIL` execution truth.

## Google technology — completed

The final hackathon path uses and demonstrates:

- **Gemini 3.5+**;
- **Google Agent Development Kit (ADK)**;
- **Google GenAI SDK (`google-genai`)**;
- **Vertex AI**;
- **FunctionGemma / Gemma**;
- **Cloud Run**;
- **Firestore**;
- **Pub/Sub**;
- Google Cloud identity / policy patterns;
- Model Armor / agentic-defense controls where integrated.

Verified submission evidence includes Gemini execution, Google agent-framework integration, Cloud Run deployment, Firestore persistence, Pub/Sub events and the live Vertex AI / FunctionGemma Judge path.

## FunctionGemma final path

For the final submission, FunctionGemma Judge Test 3 was connected to the live Vertex AI route and successfully exercised after the final production hotfix.

The hotfix:

- removed a stale dedicated Vertex DNS dependency;
- uses current endpoint discovery;
- preserves truthful model result handling;
- prevents an application HTTP 502 from incorrectly masking the probe result.

Final Judge UI integration hotfix:

```text
Rafa-Innerchispa/innerspark-workforce-ai
6808383d9f098839e5754a8405e010dd9bd28601
```

## Seven judge proofs

The Judge Console exposes seven independently runnable proofs:

1. system health and fresh correlation ID;
2. A2A discovery and connectivity;
3. live FunctionGemma / Vertex AI execution;
4. Gemini generation with a real downloadable PDF artifact;
5. ARIA natural-language interaction;
6. sovereign local AMD model inference;
7. bounded multi-agent dispatch with durable Global Live Trace evidence.

ARIA and Global Live Trace are visible together so judges can inspect what ran, where it ran and what evidence was produced.

## Local-first Resource Fabric

The sovereign compute plane includes AMD Radeon AI PRO R9700-class hardware, ROCm, vLLM and Qwen3-Coder-class local inference, plus lighter local runtimes and deterministic tools.

The routing principle is:

> **Local when it is sufficient. Cloud when it adds real value.**

## Architecture

```mermaid
flowchart TB
    WORLD[Real-world signals]
    ARIA[ARIA / InnerOS Orchestrator]
    MEM[Persistent Memory & State]
    POLICY[Identity | Policy | Approval]
    FABRIC[Resource Fabric]
    A2A[A2A Agent Fleet]
    VERIFY[Verification & Evidence]

    subgraph LOCAL[Local Sovereign Compute]
      AMD[AMD R9700 | ROCm | vLLM]
      LIGHT[Secondary local runtimes]
    end

    subgraph GOOGLE[Google Cloud]
      GEMINI[Gemini 3.5+]
      ADK[ADK / GenAI SDK]
      VERTEX[Vertex AI / FunctionGemma]
      CR[Cloud Run]
      FS[Firestore]
      PS[Pub/Sub]
    end

    WORLD --> ARIA
    ARIA <--> MEM
    ARIA --> POLICY --> FABRIC
    FABRIC --> A2A
    FABRIC --> LOCAL
    FABRIC --> GOOGLE
    A2A --> VERIFY
    LOCAL --> VERIFY
    GOOGLE --> VERIFY
    VERIFY --> MEM
```

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

Optional MCP tool surface:

```bash
./run_mcp.sh
```

Verification:

```bash
curl http://127.0.0.1:8101/status
python3 -m unittest discover -s platform/tests -p 'test_*.py'
```

Secrets are intentionally not committed.

## Pre-existing work disclosure

The wider ecosystem already contained real products and infrastructure before the event. The hackathon contribution is the unified InnerOS / ARIA enterprise fleet layer and the substantial work completed during the submission period, including durable fleet coordination, expanded A2A interoperability, Google-native execution, Resource Fabric routing, Judge Console / Global Live Trace, verification and recovery loops, persistent evidence and governance hardening.

## Final principle

**InnerOS notices what matters, chooses the right bounded intelligence and execution resource, does what it safely can, proves what happened, and brings the human back only when human authority is actually needed.**
