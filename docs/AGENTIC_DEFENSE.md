# Agentic Defense for InnerOS

InnerOS connects agents to real repositories, infrastructure, business data and external systems. That makes agent security an execution problem, not a prompt-writing problem.

This document maps the current InnerOS defense-in-depth architecture to Google Cloud's current agentic-defense direction and identifies the hackathon integration targets.

## Threat model

The main risks we design for are:

- direct prompt injection from a user;
- indirect prompt injection from email, web pages, documents or tool output;
- tool poisoning or malicious tool-returned instructions;
- sensitive data leakage in prompts/responses;
- overly broad credentials or agent identity;
- arbitrary command execution;
- concurrent agents modifying the same resource;
- runaway retries/fan-out;
- stale tasks being mistaken for active progress;
- cross-tenant data access;
- a model making a probabilistic decision where deterministic rules are required;
- an agent claiming success without evidence.

## Existing InnerOS controls

### 1. Bounded execution surfaces

Agents do not receive unrestricted shell access as the normal execution path.

InnerOS exposes constrained tools such as repository inspection, isolated worktree creation, allowlisted commands, safe file writes, cloud-provider actions, service controls and funding/operations registries.

The model proposes an action; the tool contract decides whether the action is permissible.

### 2. Repository ownership and isolation

Development operations use:

- repository authorization policies;
- explicit locks before mutation;
- isolated Git worktrees;
- non-protected work branches;
- no force-push normal path;
- test/evidence requirements;
- explicit lock release.

This reduces collisions between parallel agents and prevents a worker from casually mutating production branches.

### 3. Approval boundaries

High-impact operations can require an approval identifier or a separate human decision.

The long-term principle is:

```text
safe + reversible + policy-approved -> agent can execute
high impact / destructive / authority-bearing -> human approval required
```

### 4. Server-side secret handling

Credentials are stored in server-side vault/config surfaces and tool responses are designed not to expose raw secrets back into model context.

### 5. Tenant and identity boundaries

Business/product APIs are being moved toward server-derived authenticated tenant context rather than accepting arbitrary company identifiers from a browser or model-supplied input.

### 6. Deterministic business logic

Payroll, permissions and other high-consequence calculations remain deterministic. AI can explain, correlate, classify and investigate; it should not replace deterministic rules with probabilistic guesses.

### 7. Durable task state and anti-freeze behavior

InnerOS persists task ownership, revision and progress state. A heartbeat timestamp alone does not count as progress. Blocked work should not silently resurrect simply because a worker is alive.

### 8. Evidence before closure

Operational work can record tests, commit hashes, logs, state changes and other evidence. The objective is to close tasks based on observable results rather than agent self-report.

## Google Model Armor mapping

Google Cloud Model Armor provides runtime screening for generative and agentic AI interactions, including prompt injection/jailbreak detection, sensitive-data protection, malicious URLs, harmful content and agent/tool interaction screening.

For InnerOS, the most valuable use is at the untrusted-content boundaries:

```text
email / web / document / external MCP output
                 |
                 v
        Model Armor screening
                 |
                 v
       Executive Intelligence
                 |
                 v
      agent reasoning / tools
```

### Hackathon target

For the Google-hosted execution path:

1. create a Model Armor policy/template in the Google Cloud project;
2. enable prompt-injection/jailbreak screening;
3. enable sensitive-data screening where appropriate;
4. sanitize untrusted natural-language input before it reaches the reasoning loop;
5. sanitize model/tool output before it can become instructions for another agent;
6. record allow/block decisions in demo evidence.

We will only claim these controls as integrated after the live path is verified.

## Agent identity and least privilege

Autonomous agents should not borrow broad owner credentials.

The target Google Cloud pattern is:

- dedicated service identity for the agent/runtime;
- least-privilege IAM roles;
- separate read and mutation permissions where possible;
- restricted access to only required projects/services;
- no model-visible long-lived secrets;
- explicit policy boundary before high-impact actions.

This mirrors the local InnerOS philosophy: identity and authorization belong to the execution plane, not to natural-language instructions.

## Gateway and egress policy

Untrusted external content is one of the largest agentic risks. A future/production InnerOS gateway should maintain explicit outbound allowlists for the services required by a task instead of allowing arbitrary network destinations.

For the hackathon path, the practical objective is to demonstrate that agent tools are scoped and that cloud identities cannot mutate unrelated resources.

## Security Command Center / observability

Google Cloud's current AI Protection / Security Command Center direction includes discovery of agentic workloads and MCP servers, runtime threat detections and integration with Model Armor.

Within the hackathon timebox, InnerOS should capture enough Google-side evidence to show:

- which Cloud Run service is executing;
- which service identity it uses;
- relevant logs for the demo transaction;
- Model Armor decision evidence if integrated;
- Firestore/state mutation corresponding to the same workflow;
- no secret material in logs or screenshots.

## Demo security story

The security demo should be small and undeniable, not a security-product tour.

A useful test:

1. ingest an email/tool payload containing a harmless prompt-injection fixture;
2. show that the untrusted text is treated as data, not an instruction;
3. show the Model Armor/guardrail decision on the Google path if available;
4. show that the agent cannot bypass the tool allowlist;
5. show the legitimate action succeeding through the approved tool;
6. show evidence/audit state.

## Non-goals before submission

- Do not redesign the entire identity stack.
- Do not expose private production data for a demo.
- Do not grant broad IAM permissions merely to make a demo easier.
- Do not claim Model Armor is active until an actual request path is verified.
- Do not replace deterministic local controls with a cloud security label.

## Principle

**The model can recommend an action. The execution plane decides what the model is allowed to do.**
