# Public Repository Readiness Checklist

This checklist is the gate for presenting InnerOS Agentic Platform as a reusable public engineering project.

## Repository metadata

- [x] Clear README and architecture narrative
- [x] Contribution policy
- [x] Security policy
- [ ] Open-source license selected by owner
- [ ] Repository topics/description normalized
- [ ] Release tags and changelog cadence defined
- [ ] Issue/PR templates

## Reproducibility

- [ ] Minimal local docker/venv quickstart verified from a clean clone
- [ ] One-command or documented Temporal development bootstrap
- [ ] LangGraph example runnable without production secrets
- [ ] MCP compact-gateway example runnable with mock/sanitized upstream
- [ ] Test suite documented by subsystem
- [ ] Known limitations documented

## Security

- [ ] Secret scan clean
- [ ] History scan for accidentally committed secrets/private data
- [ ] Public `.env.example` contains placeholders only
- [ ] No personal contact details required for runtime examples
- [ ] No real production tunnel URLs
- [ ] No private network topology required for public setup
- [ ] SECURITY.md present

## Architecture clarity

Public docs should explain the strict separation:

```text
Signals
  -> NATS/event intake
  -> Temporal durable workflow
  -> LangGraph reasoning/activity
  -> MCP bounded capability
  -> local model / deterministic executor
  -> verification/evidence
  -> Mongo projection + OTel trace
```

## Public case study

Document the failure-to-convergence story with measurable evidence:

- oversized MCP catalog / context pressure;
- stale and duplicate task states;
- ACK-without-execution;
- stale locks and detached worktrees;
- local-model outages and fallback;
- OAuth/resource drift;
- scheduler overlap;
- migration to durable Temporal ownership;
- compact MCP gateway;
- branch hygiene and canonical integration.

Prefer before/after metrics over marketing claims.

## Branch cleanup gate

Before a public release:
- [ ] every remote branch classified;
- [ ] merged branches removed;
- [ ] active branches linked to open PRs/tasks;
- [ ] salvage branches converted to PRs or archived;
- [ ] no branch contains secrets or private operational data.

## License note

Do not add a permissive open-source license automatically. Choosing MIT, Apache-2.0, AGPL, BSL, or another license changes reuse and commercial rights. The repository owner must make that explicit choice before the first formal open-source release.
