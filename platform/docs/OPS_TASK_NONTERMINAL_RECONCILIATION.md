# Ops Task Nonterminal Reconciliation

This contract prevents the External Repair Agent from reporting an empty queue when Mongo still contains non-terminal work assigned to a provider.

## Source Of Truth

- Canonical tasks: `ralfia_ops_tasks`.
- Durable repair runs: `ralfia_external_repair_runs`.
- Handoffs/messages: `ralfia_agent_messages`.
- `active_runs=[]` never means `no pending work` by itself.

## Nonterminal Statuses

The nonterminal set is:

- `proposed`
- `accepted`
- `in_progress`
- `partial`
- `verification`
- `awaiting_approval`
- `blocked`

Terminal statuses are `completed`, `failed`, and `cancelled`.

## Buckets

`external_repair_agent_status()` exposes:

- `pending_nonterminal_count`
- `nonterminal_statuses`
- `nonterminal_buckets`
- `nonterminal_tasks`

Each task is classified into one bucket:

- `ACTIVE_RUN`: a durable repair run is active; monitor it.
- `ACTIVE_TASK_NO_RUN`: the task is recent and owned, but no active run exists; monitor the task state instead of claiming another task.
- `TERMINAL_PENDING_EVIDENCE`: a completed run exists while the ops task is still nonterminal; close from durable evidence.
- `STALE_RECOVERABLE`: no active run exists and the latest task activity is stale; resume or close with evidence.
- `PROPOSED`: eligible for claim if provider is ready and there are no active/recent tasks.
- `BLOCKED`: blocked without a retry/recovery signal; wait for owner or new evidence.

## Reconcile Order

`external_repair_agent_reconcile()` must run in this order:

1. Close nonterminal tasks whose durable repair run already completed.
2. Resolve terminal handoff messages.
3. Recover or mark stale active runs.
4. Record nonterminal bucket metadata without changing `updated_at`, so old tasks are not made artificially fresh.
5. Claim a proposed task only if no active run and no active/recent nonterminal task remain.

## HyperLoom Regression

If `ops_7fbd43c2f9c9` has a completed durable run or canonical evidence, reconciliation must close the task from that evidence and must not rerun the benchmark, restart vLLM, or spend cloud credits.
