# Unified Provider Execution Fabric

Updated: 2026-09-01

## Purpose

Use one canonical lifecycle for Codex, Cursor, Antigravity and future providers.
Inbox delivery is never execution. A task can enter `running` only with local
process proof or remote session proof.

## MCP entrypoint

Use:

```text
execute_provider_task(provider, title, body, repo, branch, worktree, correlation_id, dry_run=true)
```

Defaults protect credits. `dry_run=true` creates/checks the dispatch path without
launching a paid or external provider.

Use:

```text
provider_execution_fabric_status()
```

to inspect the adapter contract and per-provider readiness.

## Provider modes

| Provider | Executable state |
| --- | --- |
| Codex | `ready` only when local CLI/headless + auth are detected |
| Cursor | `remote_inbox_only` unless real headless/session proof exists |
| Antigravity | `remote_inbox_only` unless real headless/session proof exists |
| Future provider | registered by provider manifest, not core switch hacks |

## Running proof

Accepted proof types:

- `process`: requires positive PID, node and output/checkpoint evidence.
- `remote_session`: requires stable `session_id` and transport `remote_ide`,
  `a2a` or `provider_inbox`.

Without proof, the bridge returns `execution_proof_required_for_running`.

## Completion proof

Do not mark PASS/completed without evidence. Evidence should include:

- `run_id` or `dispatch_id`
- provider and transport
- started/ended timestamps
- stdout/stderr tail or remote session evidence
- files touched
- tests run and results
- commit SHA when code changed

## Cost policy

Local-first. External/cloud spend remains separately gated by explicit owner
approval, provider budget policy and apply windows.
