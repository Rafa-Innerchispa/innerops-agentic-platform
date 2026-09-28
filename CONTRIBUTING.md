# Contributing to InnerOS Agentic Platform

InnerOS is a local-first agent operations platform focused on durable execution, bounded tools, observability, recovery, and human approval.

## Canonical development flow

1. Start from current `main`.
2. Create one short-lived branch for one bounded change.
3. Keep the branch isolated from unrelated work.
4. Add or update tests.
5. Open a pull request with reproducible evidence.
6. Merge only after the change is independently reviewable.
7. Delete or archive the merged branch.
8. Treat `main` as the only canonical integration history.

A task is not complete because an agent says "done". It is complete when the accepted change is represented in `main`, evidence is attached, and the runtime state is reconciled.

## Branch naming

Use one of:

- `feat/<scope>-<short-description>`
- `fix/<scope>-<short-description>`
- `docs/<scope>-<short-description>`
- `agent/<agent>-<task-id>`

Avoid date-only branches, duplicate branches for the same task, and long-lived personal branches.

## Pull request requirements

Every PR should include:
- problem statement;
- affected subsystem;
- exact base and head SHAs;
- tests or verification commands;
- evidence of success/failure;
- operational or migration impact;
- rollback notes for runtime changes;
- security notes when MCP, OAuth, execution, secrets, or permissions are involved.

## Durable coordination architecture

Contributors should preserve the following ownership boundaries:

- **Temporal**: durable execution lifecycle, retries, waits, cancellation, terminal workflow state.
- **LangGraph**: reasoning/state graph inside an agent step or workflow activity.
- **NATS JetStream**: durable event distribution.
- **MongoDB**: operational projection, search, reporting, evidence metadata.
- **MCP**: bounded tool protocol and capability exposure.
- **OpenTelemetry**: traces and correlation.
- **Local model plane**: preferred inference path; external paid inference only when explicitly approved.

Do not create competing schedulers or duplicate task state machines without a documented migration plan.

## Public/private boundary

Public code must use sanitized examples. Real customer, network, account, phone, credential, tunnel, and production host details belong in private operational configuration, not this repository.

## Cleanup discipline

Merged branches are disposable. Valuable code belongs in `main`; valuable architectural context belongs in docs; valuable runtime evidence belongs in the evidence store. Branches are not archives.
