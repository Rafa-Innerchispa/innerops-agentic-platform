# P0 Coordination Recovery — 2026-09-29

## Scope

This branch repairs fail-open coordination behavior without deploying or
changing production data. It deliberately does **not** claim that NATS,
OpenTelemetry, LangGraph, or the compact universal MCP gateway are live until
runtime canaries prove them.

## Changes in this recovery branch

1. Temporal workers register every activity used by `OpsTaskWorkflow`.
2. New ops tasks are admitted through one deterministic Temporal workflow ID.
3. Direct terminal writes through `complete_ops_task` fail closed.
4. Heartbeats, approvals, cancellation, and candidate evidence are Temporal
   signals rather than direct Mongo lifecycle writes.
5. Local model responses no longer manufacture file, diff, or test evidence.
6. Mongo projection and durable-event failures are visible and retryable.
7. Inbox polling no longer acknowledges messages by default.
8. Durable-message persistence failures are returned to the caller.
9. Message queries raise an explicit error instead of returning a false empty
   inbox.
10. MCP session diagnostics accept a profile and compare the client against the
    projected profile rather than always comparing it to the global catalog.

## Explicitly deferred

- Enabling NATS or OpenTelemetry in production.
- Migrating legacy `open` messages and creating unique indexes.
- Replacing the local candidate generator with a real bounded coding executor.
- A generic `invoke_routed_tool` for MCP Small.

The universal compact MCP dispatcher must enforce OAuth scopes, tenant policy,
risk level, schema validation, approvals, idempotency, and audit. A generic
server-side function call without those checks would be a privilege-escalation
path and is not acceptable.

## Offline gate

Run in an isolated environment:

```bash
PYTHONPATH=platform python platform/tests/test_coordination_recovery_p0.py -v
python -m py_compile \
  platform/inneros_core_runtime/temporal_worker.py \
  platform/inneros_core_runtime/temporal_workflows.py \
  platform/inneros_core_runtime/temporal_activities.py \
  platform/inneros_core_runtime/durable_coordination_spine.py \
  platform/inneros_core_runtime/coordination_live.py
git diff --check
```

## Runtime canary plan — no production promotion yet

### Intel `.4` canary

1. Snapshot the affected Mongo collections and Temporal workflow inventory.
2. Stop task admission and automatic completion; keep read paths online.
3. Deploy the branch only to an isolated canary service/port.
4. Start one Temporal worker on a dedicated canary queue.
5. Create one task with a fixed idempotency key.
6. Confirm exactly one workflow and zero direct terminal Mongo writers.
7. Submit a candidate with no diff and verify it cannot complete.
8. Submit real bounded-executor evidence and verify the gate.
9. Send a message, poll twice without ACK, then ACK explicitly.
10. Restart the canary worker and confirm message/task recovery.

### AMD `.5`

Do not synchronize until every Intel canary passes. After synchronization,
compare the hashes of all critical runtime files before enabling failover.

## Rollback

No data migration is part of this branch. Rollback is:

1. stop the isolated canary service;
2. restore the prior service unit/environment;
3. keep the recovery branch and evidence for review.

Do not rewrite Mongo task states during rollback.