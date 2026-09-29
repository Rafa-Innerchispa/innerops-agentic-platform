# Branch, Integration, and Release Policy

## Purpose

Prevent the recurring failure mode where useful work exists only in an agent worktree, stale branch, detached checkout, or coordination message while production and `main` tell a different story.

## Source of truth

`main` is the canonical software history.

The following are not sources of truth:
- an agent saying a task is complete;
- a local worktree;
- a detached HEAD;
- a Mongo task status by itself;
- a coordination inbox message;
- an unmerged branch;
- a runtime process whose exact SHA is unknown.

## Definition of done

A code task is DONE only when all applicable conditions are true:

1. implementation exists in an isolated task branch/worktree;
2. relevant tests pass;
3. security/quality gates pass;
4. PR exists with exact SHA and evidence;
5. change is merged to `main`;
6. merged SHA is recorded in task evidence;
7. deployment/runtime is reconciled to a known SHA when deployment is part of the task;
8. temporary branch/worktree is removed after verification.

If integration is intentionally deferred, the task status must be `ready_for_integration`, not `completed`.

## Agent rule

Agents must never report "completed" for implementation work that is only present locally or only pushed to an unmerged branch.

## Branch lifecycle

- create from latest `main`;
- one task per branch;
- no unrelated staged changes;
- no global reset/clean against shared workspaces;
- merge promptly after verification;
- delete merged branches;
- close stale branches after classifying them as:
  - merged/redundant;
  - active;
  - salvage-required;
  - abandoned with evidence.

## Runtime provenance

Long-running services must expose or log:
- repository;
- commit SHA;
- build/version identifier;
- startup time;
- configuration profile name without secrets.

This allows runtime ↔ GitHub verification.

## Release tags

Once the current convergence work stabilizes, use semantic release tags:
- `v0.x.y` while interfaces are still changing;
- release notes summarizing coordination, MCP, Temporal, LangGraph, security, and migration changes.

## No duplicate orchestration ownership

Temporal is the durable execution authority. LangGraph owns agent reasoning graphs. Mongo stores projections/evidence. NATS distributes events. MCP exposes tools. Any legacy scheduler that overlaps Temporal must either delegate to Temporal or be retired through an explicit migration.

## Branch hygiene target

The remote repository should normally contain:
- `main`;
- a small number of active PR branches;
- exceptional long-lived release branches only when documented.

Do not use remote branches as historical storage. Git already has history.
