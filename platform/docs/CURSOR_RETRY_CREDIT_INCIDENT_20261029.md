# Cursor repeated execution incident, 2026-10-29 (America/Guayaquil)

Task: `ops_7039e9cc4f11`.
Correlation: `inneros-end-to-end-certification-reverse-failure-matrix-20261029`.
Owner ordered immediate stop and repair after unexpected Cursor credit use.

## Verified cause and impact

Intel's runtime differed from GitHub main. Its resume selector included failed
and verification tasks and did not enforce supersession, manual dispatch or
interactive-lane exclusions. Each two-minute tick could invoke the SDK again
after a successful submission. The shared dispatcher repeated this admission
gap. Main already contained partial protections that had not reached runtime.

Incident logs: 329 files, including 265 SDK results reporting success with
`composer-2.5`, 62 network failures, and two empty/interrupted logs. These are
execution records, not invoices. Billing/credit totals were not available.
`local_sdk` refers to local tool execution, not local model inference:
`Agent.prompt` uses Cursor credentials and a remote model.

At inspection, the task branch had 57 commits beyond origin/main, touching only
`platform/docs/ops/OPS_7039e9cc4f11_CHECKPOINT.md` and
`platform/docs/ops/OPS_7039e9cc4f11_FMEA_MATRIX.yaml`. This proves repeated
documentation changes; it is not a complete audit of all historical runtime
actions. Preserve the branch and do not roll back unrelated changes.

## Containment

- Task cancelled with owner-stop evidence, top-level and payload exclusions.
- Claim token and lease removed; prior task document saved privately.
- Replacement `ops_2362826c1698` was already completed.
- Intel headless timer stopped/disabled; offending task unit masked.
- Cursor excluded from external-repair daemon providers; other providers retained.
- No headless workers found on either node after containment.

Private evidence and rollback copies on the nodes:
`var/evidence/cursor_loop_stop_20261029/` beneath the ecosystem root.
Do not publish raw task backups, environment files or credentials.

## Repair

One admission policy is used by resume selection, dispatch and worker startup.
It rejects terminal/verification, superseded, paused, stopped, manual-only and
interactive tasks, missing claims/authorization and prior completion submissions.
Automatic dispatch has a hard budget of three reservations per task, incremented
atomically, including ordinary successful launches. Force retry does not bypass
admission or reset the budget. The worker rechecks before a paid invocation.

Runtime emergency patches preserve each node's pre-existing files instead of
copying complete newer main files over unrelated changes. The shared new policy
is identical. Original runtime hashes were checked before replacement, and
rollback copies retained. Cursor automation remains paused after repair.

## Validation

- Repository: 48 focused tests passed, including existing admission/runtime tests.
- Intel effective runtime: 27 regression tests passed.
- Live cancelled-task dispatch rejected even with force retry; direct worker
  exited before invoking SDK. Module paths confirmed the production files.
- Test invocations mocked execution; no Cursor or other paid inference needed.
- Git diff whitespace check passed.

Reactivation requires an explicit owner order and reviewed deployment. Do not
remove the containment controls merely because tests passed or a PR was merged.
