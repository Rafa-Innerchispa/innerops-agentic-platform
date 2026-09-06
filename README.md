# InnerOS - ARIA Enterprise Agent Fleet

> **An AI operating system for a real small technology company.**
>
> InnerOS watches signals, remembers context, delegates work, executes through bounded tools, verifies outcomes, recovers stalled work, and brings the human back only when the human is actually needed.

**All Things Agentic Hackathon 2026 - Fortified Enterprise Fleet**

## Judges

**Start here:** [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md)  
**Live Judge Console:** https://inneros.creatorcore.ai/app/judge  
**Devpost:** https://devpost.com/software/innerops-aria-enterprise-agent-fleet

This public repository is the **single canonical hackathon source of truth**. Existing products such as Workforce are real integration targets and operational proof, but judges do not need a second repository to evaluate InnerOS.

---

## Why this exists

InnerOS did not start as a hackathon prompt.

It grew from a practical problem: one person becoming the bottleneck of a small technology company while simultaneously handling customers, field operations, software development, infrastructure, cloud services, billing, funding opportunities, hackathons, email, vendors, and new products.

Building isolated AI assistants helped, but it also created a new problem: **someone still had to watch the assistants, remember the deadlines, notice the important email, check whether development stalled, recover broken services, and decide what should happen next.**

InnerOS is an attempt to remove that coordination burden.

The core operating loop is:

```text
signal -> relevance -> memory -> decision -> delegation
       -> execution -> verification -> recovery -> evidence -> learning
```

The scarce resource we are optimizing for is not tokens. It is **human attention**.

---

## What InnerOS does

InnerOS receives signals from real operational systems instead of waiting for a perfect user prompt.

Signals can come from:

- email and opportunity feeds;
- GitHub/GitLab repositories;
- infrastructure and service health;
- cloud providers and billing/credit events;
- hackathon and funding deadlines;
- business systems;
- workforce and physical-access events;
- messaging channels;
- other agents.

ARIA, the agent fleet, then coordinates the next safe action:

1. classify the signal in the context of current projects and priorities;
2. retrieve persistent operational context;
3. select the appropriate specialist capability;
4. acquire ownership/locks where required;
5. execute through scoped deterministic tools;
6. route sensitive actions through approval policy;
7. verify the outcome;
8. persist evidence and state;
9. recover or escalate stalled work;
10. suppress duplicate noise once the loop is closed.

This is deliberately different from a chat loop. **Many agent demos begin with a prompt. InnerOS begins with the world.**

---

## Architecture at a glance

```mermaid
flowchart TB
    WORLD[Real-world signals\nEmail | Git | Cloud | Devices | Business | Deadlines]
    INTEL[Executive Intelligence\nRelevance | Deadline | Value | Risk | Dedupe]
    MEM[Persistent Memory & Operational State]
    ARIA[ARIA Orchestrator / Agent Registry]
    POLICY[Identity | Policy | Approval | Guardrails]
    EXEC[Bounded Tool Execution]
    VERIFY[Verification | Evidence | Observability]

    subgraph LOCAL[Local Sovereign Compute]
      NV[NVIDIA Node\nRTX 3060 12GB\nOllama + operational services]
      AMD[AMD Node\nRadeon AI PRO R9700\nROCm + vLLM]
    end

    subgraph GOOGLE[Google Cloud Plane]
      GEMINI[Gemini 3.5+]
      ADK[Google Agent Framework\nADK / GenAI SDK]
      CR[Cloud Run]
      FS[Firestore]
      PS[Pub/Sub where appropriate]
      MA[Model Armor / Agentic Defense]
    end

    CHATGPT[ChatGPT\nHuman-facing engineering & operations interface]
    MCP[InnerOS MCP / Tool Layer]

    WORLD --> INTEL --> MEM --> ARIA
    MEM <--> ARIA
    ARIA --> POLICY --> EXEC --> VERIFY --> MEM

    ARIA <--> NV
    ARIA <--> AMD
    ARIA <--> GEMINI
    GEMINI <--> ADK
    ADK --> CR
    CR <--> FS
    CR <--> PS
    POLICY <--> MA

    CHATGPT <--> MCP <--> ARIA
```

---

## Two-node local AI infrastructure

InnerOS is not running on one workstation and it is not cloud-only. The local plane currently spans two heterogeneous servers.

### NVIDIA node - `ralphi-ia-ver-10`

Live hardware discovery confirms:

- Ubuntu 24.04 LTS;
- 31 GiB system RAM;
- **NVIDIA GeForce RTX 3060 with 12,288 MiB VRAM**;
- Ollama local model runtime;
- MongoDB, Qdrant, n8n, Home Assistant and supporting data/integration services;
- MCP, authentication, browser automation, messaging and operational services.

This node remains important because much of the ecosystem began here and many long-running services still live on it.

### AMD node - `ralfiia-amd`

Live hardware/runtime discovery confirms:

- AMD-based Linux server;
- **AMD Radeon AI PRO R9700 (RDNA4 / gfx1201)**;
- approximately 32 GiB class VRAM;
- ROCm runtime;
- vLLM OpenAI-compatible serving;
- larger local coding/inference workloads.

At the time of this README update, the local vLLM plane was serving a Qwen3 Coder 30B-class quantized model.

The two nodes are treated as a resource fabric. Work is routed according to capability, privacy, cost, available hardware and risk.

> **Cloud when it adds value. Local when it does not.**

---

## ChatGPT + Gemini: model-agnostic by design

A meaningful part of InnerOS has been built and operated through **ChatGPT as the human-facing command, engineering and reasoning interface**, connected to the system through the InnerOS MCP/tool layer.

That is intentionally documented rather than hidden simply because this hackathon is hosted by Google.

For the All Things Agentic Hackathon, the Google-native path uses **Gemini 3.5+**, Google agent tooling, and Google Cloud infrastructure. Gemini is an important reasoning/runtime participant, but InnerOS is not designed around vendor lock-in.

The architecture separates:

- model reasoning;
- persistent memory and state;
- identity and access;
- deterministic business rules;
- scoped tools;
- execution ownership;
- verification;
- human approval.

This allows local models, Gemini, ChatGPT-assisted operations and other authorized providers to participate behind the same operational controls.

---

## ARIA is a fleet, not a set of personas

ARIA coordinates specialized operational capabilities with distinct scopes. Current capabilities include areas such as:

- executive signal and opportunity intelligence;
- hackathon and funding monitoring;
- local model/runtime routing;
- software-development execution;
- repository ownership, locks and isolated Git worktrees;
- testing, evidence and pull-request workflows;
- infrastructure/service monitoring and recovery;
- Google Cloud and Cloudflare operations;
- persistent memory and coordination;
- Discord/messaging surfaces;
- browser automation;
- workforce, payroll, access and credential domains;
- reporting and administrative operations.

The system deliberately avoids treating every problem as an LLM problem. Deterministic operations stay deterministic; models are used for classification, planning, synthesis and context-aware decisions.

---

## Fortified Enterprise Fleet mapping

### Discovery & lifecycle

InnerOS maintains an agent/capability catalog instead of hard-coding the whole system into one giant prompt. Capabilities can be discovered and routed by task class.

### Long-running execution

Operational tasks use persistent state, ownership, revisions, heartbeats, retries and recovery. A timestamp alone does not count as progress; stalled work can be distinguished from actual forward motion.

### Persistent memory

Project decisions, operational context and evidence survive beyond individual chat sessions.

### Identity & governance

Execution is constrained by scoped tool surfaces, repository authorization, approval boundaries, tenant context and secret-handling rules.

### Observability

Actions produce task state, logs and evidence so an operator can reconstruct what happened instead of trusting an opaque success message.

---

## Agentic Defense

Real autonomy requires real security boundaries.

InnerOS already uses several defense-in-depth patterns:

- allowlisted commands instead of arbitrary shell execution;
- repository policies and isolated worktrees;
- RACB-style ownership/locking to prevent concurrent collisions;
- approval gates for high-impact mutations;
- secrets stored server-side instead of returned to agents;
- tenant isolation and server-derived identity where applicable;
- deterministic financial/payroll rules outside probabilistic model output;
- audit/evidence capture;
- stalled-worker detection and bounded recovery.

For the Google-hosted path, the hackathon work is also mapping and integrating Google's agentic-defense capabilities, including:

- **Model Armor** for prompt injection, jailbreak, tool-output and sensitive-data screening where applicable;
- least-privilege IAM / agent identity;
- policy-aware gateways and bounded egress/tool access;
- Security Command Center / observability evidence where practical within the hackathon scope.

See [`docs/AGENTIC_DEFENSE.md`](docs/AGENTIC_DEFENSE.md).

---

## AMD / ROCm strategy

The AMD node is a first-class part of the architecture.

AMD's newly released **AMD Skills** concept is especially relevant because it brings AMD-validated operational knowledge into agent coding tools using a reusable skills format. InnerOS is evaluating this as a safer alternative to letting every agent improvise ROCm operations.

We are deliberately **not** performing a risky production ROCm major-version upgrade immediately before the hackathon deadline. The priority is reusable skills, diagnostics, evidence and bounded experiments that do not destabilize the working R9700 runtime.

See [`docs/AMD_ROCM_STRATEGY.md`](docs/AMD_ROCM_STRATEGY.md).

---

## Workforce is proof, not the whole product

InnerOS grew out of real operational software.

One product built and operated in this environment is **Workforce**, a multi-tenant workforce platform covering attendance, schedules, mobile check-ins, biometrics, incidents, reporting and deterministic pre-payroll.

The relationship is:

```text
InnerOS helps operate the company
        -> the company builds Workforce
        -> Workforce automates customer operations
```

Workforce remains a commercial P0 for a real customer, but the hackathon project is the broader InnerOS/ARIA operating layer.

---

## Google technology used / targeted in the hackathon path

- Gemini 3.5 or newer;
- Google Agent Development Kit (ADK) and/or Google GenAI SDK;
- Google Cloud Run;
- Cloud Firestore;
- Pub/Sub where asynchronous event distribution is useful;
- Google Cloud IAM/agent identity patterns;
- Model Armor and agentic-defense controls where integrated;
- Google Cloud logs/console evidence for production-readiness proof.

The project has **$150 in Google Cloud hackathon credits** reserved for bounded deployment, validation, security/observability and demo workloads.

---

## Pre-existing work disclosure

This repository and project are explicit about prior work.

Before the All Things Agentic submission period, the ecosystem already included workforce functionality, local AI infrastructure, MCP integrations, server services and earlier experiments with agents.

The hackathon contribution is the **new unified InnerOS/ARIA enterprise operating layer** built during the submission period, including work such as:

- expanded multi-agent orchestration;
- durable execution state;
- ownership and locking;
- local/cloud routing;
- recovery and anti-freeze behavior;
- enterprise governance boundaries;
- cross-domain coordination;
- Google Cloud deployment path;
- executive signal-to-action intelligence;
- observability/evidence improvements;
- the new coherent product architecture and demo path.

Pre-existing components are foundations, not falsely claimed as new hackathon work.

---

## Reproducible local setup

This repository contains a large operational system. The minimal local runtime can be started independently of the full production environment.

### Requirements

- Linux recommended;
- Python 3.12+;
- Git;
- MongoDB for the full persistent operational path;
- environment variables from `platform/.env.example`;
- optional provider credentials only for the integrations you intend to test.

### 1. Clone

```bash
git clone https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git
cd innerops-agentic-platform/platform
```

### 2. Create environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill only the environment variables required for the integration being exercised. Do not commit secrets.

### 3. Start the core API

```bash
./run.sh
```

Default local API port:

```text
8101
```

### 4. Start MCP/tool surface when required

```bash
./run_mcp.sh
```

Default MCP port:

```text
8102
```

### 5. Verify

```bash
curl http://127.0.0.1:8101/status
```

### 6. Run the bounded regression suite

From the repository root with the virtual environment active:

```bash
python3 -m unittest discover -s platform/tests -p 'test_*.py'
```

Individual hackathon-focused tests can also be run directly as they are added.

---

## Cloud deployment evidence

The hackathon build has a Cloud Run deployment in Google Cloud project `innerops-agentic-platform`, region `us-central1`, with persistent state configured for Firestore on the cloud path.

The final submission/demo will show:

- Cloud Run service/revision evidence;
- a live `.run.app` endpoint or console evidence;
- Firestore/state updates;
- Gemini/Google agent execution evidence;
- the autonomous workflow and verification trail.

---

## Demo thesis

The demo should not tour hundreds of tools.

It should prove one thing beyond argument:

> **InnerOS notices something the human is not watching, understands why it matters, delegates the work, takes the safe actions it is allowed to take, verifies the result, and asks the human only for the decision that genuinely requires them.**

The strongest candidate is the Executive Intelligence workflow built from real incoming email/opportunity/credit signals.

---

## Documentation

- [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md) - single entrypoint for evaluation
- [`docs/THE_STORY.md`](docs/THE_STORY.md) - the lived story behind InnerOS
- [`docs/AGENTIC_DEFENSE.md`](docs/AGENTIC_DEFENSE.md) - security/governance mapping
- [`docs/AMD_ROCM_STRATEGY.md`](docs/AMD_ROCM_STRATEGY.md) - AMD Skills and ROCm adoption strategy
- [`docs/ALL_THINGS_AGENTIC.md`](docs/ALL_THINGS_AGENTIC.md) - submission scope, requirements and evidence checklist
- `platform/README.md` - legacy/core MCP runtime notes retained for historical/technical context

---

## Final principle

**InnerOS notices what matters, does what it safely can, and brings the human back only when the human is actually needed.**
