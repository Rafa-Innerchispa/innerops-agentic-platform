# RalfIA Agent Coordination Bus (RACB)

**Protocol:** RalfIA Coordination Protocol (RCP)  
**Version:** 1.0.0  
**State:** staging, backward-compatible, not deployed to production

## Components

- **RACB:** message, task, lock and audit implementation.
- **RCP:** mandatory communication and lifecycle rules.
- **Coordination Hub:** MongoDB canonical state plus Markdown projections.

MongoDB is the delivery and state source of truth. Markdown is a readable
projection and must never be treated as stronger evidence than MongoDB.

## Message envelope

```json
{
  "message_id": "msg_123",
  "correlation_id": "femar-quote-20260717",
  "from_agent": "CHATGPT",
  "target_agent": "codex",
  "type": "task",
  "priority": "high",
  "payload": {},
  "reply_to": null,
  "idempotency_key": "femar-quote-20260717:codex:p0",
  "status": "open",
  "schema_version": 3
}
```

Receiving a message does not mean it was read. `ack_agent_message` changes
`open` to `acknowledged`; it does not complete the associated task.

## Task lifecycle

```text
proposed -> accepted -> in_progress
                         |-> blocked -> in_progress
                         |-> awaiting_approval -> verification
                         |-> verification -> completed | partial | failed
                         |-> cancelled
```

Terminal work requires evidence. `completed` additionally requires a result of
`PASS`, `OK` or `COMPLETED`.

## Ownership and revisions

- A task has at most one owner.
- Another agent must receive an explicit handoff before changing owned work.
- Every transition increments `revision`.
- Writers may provide `expected_revision`; a mismatch fails closed.
- Repeating an already-applied transition is idempotent.

## Resource locks

`manage_coordination_lock` groups lock operations:

- `acquire`
- `renew`
- `release`
- `inspect`
- `list`

Locks are leases with an expiry. Conflicting attempts are recorded in
`ralfia_coordination_conflicts`. Expired leases may be acquired by another
agent. Forced handoff is auditable and should be exceptional.

## Capability routing

`route_mcp_tools` selects a bounded profile using intent signals, scopes and a
risk ceiling. The legacy global endpoint remains available during migration.
Profiles must pass validation: known tools only, no duplicates, and no profile
may exceed its declared maximum.

## Persistent A2A Integration And Local-First Rule

A2A is the durable routing facade over RACB, not a second source of truth. Existing tasks keep their RACB `task_id`; new delegations use `a2a_dispatch`, which creates or links an ops task and stores projection state. Agents must preserve `correlation_id`, ACK the live inbox, move task state with RACB revisions, and publish completion or blockers back to MCP.

Default execution is local-first: AMD vLLM, Intel Ollama and governed local agents are preferred for bounded reasoning, tests, probes and development support. Cloud routes stay approval-gated when they create cost or infrastructure.

## Migration

`migrate_racb_records` defaults to `dry_run=true`. The dry run reports exact
counts and sample patches. Applying a migration requires administrative scope
and a reviewed backup. Never apply migration and production deployment in the
same change window.

## Definition of done

A task is not complete because an agent says so. Closure requires:

1. valid lifecycle transition;
2. current ownership or explicit handoff;
3. matching revision;
4. required evidence;
5. tests or externally verifiable output;
6. coordination event and task update.
