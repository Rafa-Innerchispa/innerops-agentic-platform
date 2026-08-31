# InnerOS — The Self-Healing Agentic Operating System

> A local-first, self-healing enterprise agent fleet that routes work across Gemini, Google Cloud, sovereign local models, A2A agents, and bounded operational tools with durable state and auditable evidence.

**All Things Agentic Hackathon 2026 — Fortified Enterprise Fleet**

## Final hackathon snapshot

This repository contains the canonical InnerOS / ARIA hackathon source.

For judging, use the frozen branch:

```text
hackathon-freeze-20260831
```

The submission is intentionally frozen so normal product development can continue later without changing the version evaluated by judges.

**Start here:** [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md)  
**Hackathon evidence map:** [`docs/ALL_THINGS_AGENTIC.md`](docs/ALL_THINGS_AGENTIC.md)  
**Live Judge Console:** https://inneros.creatorcore.ai/app/judge  
**Judge login:** https://inneros.creatorcore.ai/app/login?judge=1  
**Devpost:** https://devpost.com/software/innerops-aria-enterprise-agent-fleet

Judge credentials:

- Username: `HACKATHON-JUDGE` or `DEVPOST-JUDGE`
- Password: `demo123`

---

## Why InnerOS exists

InnerOS grew from a practical problem: one person becoming the coordination bottleneck of a real technology company while simultaneously handling customers, field operations, software development, infrastructure, cloud services, billing, vendors, deadlines, email, funding opportunities, hackathons, and new products.

Building isolated AI assistants helped, but created another problem: someone still had to watch the assistants, remember context, detect stalled work, decide what mattered, and verify whether anything actually finished.

InnerOS is the operating layer built to remove that coordination burden.

The core loop is:

```text
signal -> relevance -> memory -> decision -> delegation
       -> execution -> verification -> recovery -> evidence -> learning
```

The scarce resource we optimize for is not tokens. It is **human attention**.

---

## What InnerOS does

InnerOS coordinates real operational work across persistent state, specialized agents, local AI, Google Cloud, and deterministic tools.

A signal can come from a user, another agent, infrastructure, repositories, email, business systems, deadlines, cloud events, or devices.

ARIA then:

1. interprets the signal in current operational context;
2. retrieves persistent state and knowledge;
3. discovers an approved agent or capability;
4. applies identity, policy, locking, and approval boundaries;
5. chooses the appropriate local or cloud execution resource;
6. executes through bounded tools;
7. verifies the result;
8. persists evidence and state;
9. recovers stalled work or escalates only when human authority is required.

InnerOS is therefore not a chatbot collection. It is an agent operating layer.

---

## Fortified Enterprise Fleet mapping

### Discovery & lifecycle

- canonical agent / capability registry;
- A2A Agent Cards;
- durable task lifecycle state;
- capability-based routing instead of one giant prompt.

### Core execution & state

- durable `ops_task` state;
- correlation IDs;
- ownership and revision checks;
- heartbeats;
- bounded retries and recovery;
- persistent operational context;
- isolated Git worktrees for engineering tasks.

Lifecycle truth is explicit:

```text
proposed -> accepted -> in_progress -> verification
         -> completed | blocked | partial
```

Inbox delivery is never treated as task completion.

### Security & governance

- scoped and allowlisted tools;
- server-side secret handling;
- tenant and identity boundaries;
- repository locks;
- approval gates for high-impact operations;
- bounded execution budgets;
- explicit truth states preventing degraded or simulated work from becoming a verified PASS.

### Telemetry

- Global Live Trace;
- correlation IDs;
- provider / model / runtime / node provenance;
- latency and status;
- task / message / agent IDs;
- evidence references;
- `PASS / PARTIAL / FAIL / DEGRADED` truth states.

---

## Local-first Resource Fabric

Agents request capabilities rather than hard-coding a machine or vendor.

The sovereign AI plane includes:

- AMD Radeon AI PRO R9700-class GPU;
- ROCm;
- vLLM;
- Qwen3-Coder-class local inference;
- secondary local runtimes for lighter workloads;
- deterministic tools when no LLM is required.

The routing principle is simple:

> **Local when it is sufficient. Cloud when it adds real value.**

This lets the same bounded agent semantics run across local infrastructure, Gemini / Google Cloud, or other approved resources without rewriting the workflow.

---

## Google technology used

Google Cloud is a real execution plane in InnerOS, not a decorative integration.

The final hackathon path uses and demonstrates:

- **Gemini 3.5+**;
- **Google Agent Development Kit (ADK)**;
- **Google GenAI SDK (`google-genai`)**;
- **Vertex AI**;
- **FunctionGemma / Gemma integration**;
- **Cloud Run**;
- **Firestore**;
- **Pub/Sub**;
- Google Cloud identity / policy patterns;
- Model Armor / agentic-defense controls where integrated.

Verified hackathon evidence includes Gemini invocation, Cloud Run deployment, Firestore persistence, Pub/Sub events, Google agent-framework integration, and Vertex / FunctionGemma routing.

---

## FunctionGemma final state

FunctionGemma was deployed and proven through Vertex AI / Model Garden during the hackathon.

An earlier deployment was intentionally removed after proof was captured to avoid idle GPU cost. For the final submission window, the FunctionGemma route was reconnected for live Judge Test 3 verification.

The final production hotfix:

- removed reliance on a stale dedicated Vertex DNS value;
- uses fresh endpoint discovery for the live probe;
- prevents a truthful `PARTIAL` result from being incorrectly converted into HTTP 502;
- preserves the rule that a real Vertex failure must never become a fake PASS.

The final Judge integration hotfix is preserved at:

```text
Rafa-Innerchispa/innerspark-workforce-ai
commit 6808383d9f098839e5754a8405e010dd9bd28601
```

This repository remains the canonical hackathon runtime. The integration commit above is deployment evidence for the live Judge UI hosted inside the existing operational application shell.

---

## Judge Console

The Judge Console is the evidence surface for the submission.

It presents ARIA and the Global Live Trace together and provides seven independently runnable proofs:

1. system health and fresh correlation ID;
2. A2A agent discovery and connectivity;
3. FunctionGemma / Vertex AI live probe;
4. Gemini generation with a real downloadable PDF artifact;
5. ARIA arbitrary natural-language challenge;
6. local-first AMD model inference;
7. bounded multi-agent dispatch with durable trace evidence.

The Judge experience is designed around one rule:

> A visible PASS must correspond to real execution evidence.

Historical, unavailable, degraded, partial, failed, or dry-run states are labeled truthfully.

---

## Architecture at a glance

```mermaid
flowchart TB
    WORLD[Real-world signals]
    ARIA[ARIA / InnerOS Orchestrator]
    MEM[Persistent Memory & State]
    POLICY[Identity | Policy | Approval]
    FABRIC[Resource Fabric]
    A2A[A2A Agent Fleet]
    TOOLS[Bounded Tools]
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
    FABRIC --> TOOLS
    FABRIC --> LOCAL
    FABRIC --> GOOGLE
    A2A --> VERIFY
    TOOLS --> VERIFY
    LOCAL --> VERIFY
    GOOGLE --> VERIFY
    VERIFY --> MEM
```

---

## Reproducible setup

### Requirements

- Linux recommended;
- Python 3.12+;
- Git;
- MongoDB for the full persistent path;
- environment variables from `platform/.env.example`;
- provider credentials only for the integrations being exercised.

### Clone the exact hackathon snapshot

```bash
git clone https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git
cd innerops-agentic-platform
git checkout hackathon-freeze-20260831
```

### Create the environment

```bash
cd platform
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Do not commit secrets.

### Start the core API

```bash
./run.sh
```

Default local API:

```text
http://127.0.0.1:8101
```

### Start the MCP / tool surface when required

```bash
./run_mcp.sh
```

Default MCP endpoint:

```text
http://127.0.0.1:8102
```

### Verify

```bash
curl http://127.0.0.1:8101/status
```

### Run the bounded regression suite

From the repository root with the virtual environment active:

```bash
python3 -m unittest discover -s platform/tests -p 'test_*.py'
```

---

## Pre-existing work disclosure

The broader ecosystem already contained real products, local AI infrastructure, MCP integrations, server services, and earlier agent experiments before this hackathon.

The hackathon contribution is the new unified InnerOS / ARIA enterprise fleet layer and the substantial work completed during the submission period, including:

- durable fleet coordination;
- expanded A2A interoperability;
- Google-native Gemini / ADK / GenAI paths;
- Resource Fabric local/cloud routing;
- Judge Console and Global Live Trace;
- bounded engineering-agent execution;
- verification and recovery loops;
- persistent evidence;
- security and governance hardening;
- clearer truth semantics across execution planes.

Pre-existing components are foundations, not falsely claimed as new hackathon work.

---

## Documentation

- [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md) — judge entrypoint and final testing instructions
- [`docs/ALL_THINGS_AGENTIC.md`](docs/ALL_THINGS_AGENTIC.md) — requirements and final evidence mapping
- [`docs/THE_STORY.md`](docs/THE_STORY.md) — origin and product story
- [`docs/AGENTIC_DEFENSE.md`](docs/AGENTIC_DEFENSE.md) — security and governance mapping
- [`docs/AMD_ROCM_STRATEGY.md`](docs/AMD_ROCM_STRATEGY.md) — AMD / ROCm strategy
- `platform/README.md` — lower-level runtime notes

---

## Final principle

**InnerOS notices what matters, chooses the right bounded intelligence and execution resource, does what it safely can, proves what happened, and brings the human back only when the human is actually needed.**
