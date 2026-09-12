# InnerOS Project Lifecycle Standard

## Purpose

Every InnerChispa project must remain easy to resume, test, deploy and present without a last-minute archaeology expedition through forgotten branches.

## 1. Local-first is the default

- Development, coding, tests, inference and routine automation use local resources first.
- Resource Fabric / Dev Swarm should prefer the registered local provider and model for the task class.
- External/cloud execution is a fallback, not the default. Paid or metered execution must be justified, auditable and gated where required.
- A project must not embed a cloud dependency merely because a hackathon introduced it.

## 2. `main` is the product truth

- `main` must represent the best tested and integrated product state.
- Work branches and worktrees are temporary implementation surfaces, not alternate product histories.
- Passing tests on a work branch is not completion.
- A development task may become `completed` only when its exact tested commit is present in the canonical target branch and that integration is verified.
- Integration Guardian may perform only a non-force fast-forward push when the remote canonical branch is an ancestor of the tested commit and the verified worktree is clean.
- If the remote advanced/diverged, the worktree is dirty, branch protection rejects the push, or post-push verification fails, the task remains in verification with explicit integration evidence.
- Force-push to a canonical target is forbidden.

## 3. GitHub and physical server are both mandatory

Every active project must have:

1. a canonical GitHub repository;
2. a trusted physical checkout/runtime path on the InnerOS server;
3. a Project Runtime Registry binding between `project_id`, repository and node paths;
4. a known canonical branch and exact commit SHA;
5. observable Git alignment evidence: local HEAD, `origin/main`, dirty state and remote/repository match.

A project is not operationally healthy when GitHub and the server silently contain different product states.

## 4. Branch policy

### Normal product work

`main` -> short-lived work branch/worktree -> tests -> Integration Guardian -> canonical integration -> cleanup.

A branch with useful commits that are not integrated is unfinished work, even if its feature works.

### Hackathons

- `main` remains the real product and reusable platform truth.
- `hackathon/<event>` contains only the contest-specific delta that should not become product behavior automatically.
- Work created for a hackathon can target `hackathon/<event>` explicitly. Integration Guardian may fast-forward that explicit hackathon target, but never promotes it to `main` automatically.
- Generic improvements, providers, adapters, infrastructure, security fixes and reusable capabilities discovered during a hackathon must be promoted independently to the product/platform `main` as soon as they are tested.
- The submitted hackathon state is frozen by exact SHA/tag and evidence. The hackathon branch must not become a second long-lived product line by accident.

## 5. New technology is a platform capability

When a project introduces a new API, model provider, device integration, protocol, connector or useful technology:

1. register it in the Technology/Connector Registry;
2. keep secrets in the canonical server-side vault;
3. expose a reusable capability through Resource Fabric, MCP or a stable internal API;
4. make the first project consume that capability rather than own a private implementation;
5. document local-first/fallback behavior and tests.

Hackathons follow the same rule. Sponsor-specific presentation code can remain in the hackathon delta; reusable capability code belongs to the platform/product line.

## 6. Project creation / bootstrap gate

A newly created project is not `READY` until all of the following are true:

- GitHub repository exists or the approved canonical remote is reachable;
- physical local checkout exists under a trusted path;
- `origin` points to the expected repository;
- Project Runtime Registry contains the repo/path binding;
- canonical branch is known;
- local and remote SHA state is observable;
- project continuity file exists for substantial active projects;
- execution policy is local-first unless an explicit exception is recorded.

Partial bootstrap must be reported as partial/blocked with the exact reconciliation action. Never claim a project is ready merely because one side was created.

## 7. Development close gate

A coding task is complete only when evidence proves:

- implementation exists;
- required tests pass;
- exact tested commit is recorded;
- commit is integrated in the canonical target;
- remote canonical target is re-read after integration;
- no force push was used;
- task evidence records target, before/after SHA and integration result.

Anything less remains `verification`, `blocked` or `integration_pending`.

## 8. New-session bootstrap

Before modifying an existing project, an agent/session must:

1. read coordination live state and the project continuity file;
2. resolve the project through Project Runtime Registry;
3. inspect canonical GitHub/main state and the registered local checkout;
4. check live locks/worktrees/tasks;
5. continue existing work rather than create a parallel implementation;
6. preserve local-first routing;
7. after successful bounded work, integrate immediately instead of leaving a useful branch behind.

## 9. Truth boundary

Branches remain useful for isolation and review. They are not forbidden. Branch accumulation is forbidden as a substitute for integration discipline. The goal is not "never branch"; it is "never lose useful work outside canonical truth."
