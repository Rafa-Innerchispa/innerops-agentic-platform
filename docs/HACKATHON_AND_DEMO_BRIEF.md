# Hackathon and Demo Brief

## One-line description

InnerOS is a local-first agent operations platform that turns fragile AI-agent loops into durable, observable workflows with bounded tools and human approval.

## Problem

Most agent demos work while a chat session is alive.

Real operations fail differently:
- tasks outlive sessions;
- workers crash;
- models go offline;
- branches diverge;
- tools multiply;
- permissions drift;
- duplicate workers claim the same job;
- an ACK is mistaken for execution;
- a task says completed without reproducible evidence.

InnerOS is designed around those failures.

## Technical thesis

```text
signal
  -> NATS / event intake
  -> Temporal durable workflow
  -> LangGraph reasoning
  -> bounded MCP capability
  -> local model or deterministic executor
  -> verification
  -> evidence + OTel trace
  -> Mongo projection
  -> human escalation only when needed
```

## What to demonstrate

Do not show hundreds of tools.

Show one complete operational loop:

1. receive a real or sanitized event;
2. create a durable workflow;
3. route reasoning to a local model;
4. execute one bounded MCP action;
5. simulate or survive a worker/model interruption;
6. recover;
7. verify the action;
8. close with evidence;
9. show that the human was only asked for a genuinely sensitive decision.

## Differentiators

- local-first;
- heterogeneous AMD/NVIDIA/Intel execution;
- durable Temporal workflows;
- LangGraph agent reasoning;
- compact MCP capability routing;
- human approval boundaries;
- evidence-driven completion;
- real operational use, not only a demo prompt;
- open-source Apache-2.0 core.

## Evidence judges should see

- repository commit history;
- test results;
- exact workflow/task state;
- recovery after failure;
- OTel trace or equivalent correlated evidence;
- model-route evidence;
- bounded tool authorization;
- final terminal state;
- public architecture documentation.

## Suggested pitch

InnerOS started because operating a company with many AI agents created a second management problem: somebody still had to supervise the agents.

We rebuilt the coordination layer around durable execution, bounded capabilities, local models, evidence, and recovery. The goal is not more autonomous chatter. The goal is less human supervision.
