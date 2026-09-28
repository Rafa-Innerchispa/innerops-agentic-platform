# Launch and Release Guide

## Project identity

**Project:** InnerOS Agentic Platform  
**License:** Apache-2.0  
**Canonical branch:** `main`  
**Owner:** InnerChispa LLC

## Positioning

InnerOS is a local-first agent operations platform for durable execution,
bounded tool access, human approval, evidence, recovery, and model routing.

The public launch should emphasize the engineering problem solved rather than
generic "multi-agent AI" messaging:

> Durable local-first agent operations with Temporal, LangGraph, MCP,
> NATS JetStream, OpenTelemetry, and local LLM routing.

## Release gate

A public release candidate is ready when:

1. `main` contains all accepted product changes;
2. active branches map to active PRs/tasks;
3. merged and redundant branches are pruned;
4. clean-clone bootstrap succeeds;
5. focused Temporal/LangGraph/MCP/coordination tests pass;
6. secret/privacy scan is clean or historical exposures are documented and remediated;
7. public examples contain placeholders only;
8. known limitations are documented;
9. release notes summarize architecture, security, migration, and remaining limitations.

## Suggested first release

Use `v0.1.0` for the first formal public release because interfaces are still
converging.

Suggested release title:

**InnerOS v0.1.0 - Durable Local-First Agent Operations**

Suggested release highlights:

- Temporal-backed durable task execution;
- LangGraph reasoning and actor-critic flow;
- compact MCP capability routing;
- local AMD vLLM with Intel Ollama fallback;
- NATS JetStream event distribution;
- OpenTelemetry trace propagation;
- bounded execution and human approval;
- repository/task lifecycle convergence;
- branch hygiene and reproducible evidence.

## Hackathon/demo framing

Demonstrate one complete path:

```text
real signal
  -> relevance decision
  -> durable Temporal workflow
  -> LangGraph reasoning
  -> bounded MCP tool
  -> local execution
  -> verification/evidence
  -> terminal state
  -> human escalation only when required
```

Do not demo a catalog of hundreds of tools. Demo a closed loop with evidence.
