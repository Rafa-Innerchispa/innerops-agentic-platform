# ARIA Agent Contract v0.1

Each InnerOps agent is registered rather than discovered implicitly.

```yaml
agent_id: innerops.<domain>.<name>
version: 0.1.0
owner: innerops
domain: workforce|payroll|access|credentials|visitors|platform
runtime: cloud-run
model_policy:
  provider: google
  family: gemini
capabilities: []
tools: []
required_scopes: []
approval:
  mode: auto|human_required|policy_dependent
memory:
  read: []
  write: []
observability:
  traces: true
  tool_audit: true
```

## Required execution envelope

Every invocation carries `task_id`, `correlation_id`, `trace_id`, `actor`, `agent_id`, `agent_version`, `requested_capability`, `policy_context`, `input`, `created_at` and an idempotency key for mutating actions.

## Result envelope

Every result reports status, structured output, tool evidence, policy decisions, timings and whether human approval was requested or consumed.

The model never receives more authority than the registered agent contract. Tool authorization is enforced outside model-generated text.
