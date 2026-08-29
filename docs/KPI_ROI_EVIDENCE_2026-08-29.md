# InnerOS KPI / ROI Evidence Baseline — 2026-08-29

## Purpose

This document defines an auditable KPI baseline for InnerOS. The central metric is **Human Hours Returned (HHR)**: human time demonstrably avoided because InnerOS performed, recovered, verified, or coordinated work that otherwise required manual effort.

InnerOS intentionally separates operational activity from business value. Agent runs, retries, heartbeats and automated repairs are not automatically counted as productivity or savings.

## Evidence classes

Every productivity baseline must be labelled:

- `measured`: directly measured before/after or backed by reproducible operational evidence.
- `estimated`: a reasoned estimate with assumptions documented.
- `inferred`: calculated from indirect telemetry.
- `manual`: supplied by an operator/runbook but not independently measured.

Only `measured` + `verified=true` contributes to **Verified Human Hours Returned**.

## Current measured productivity baseline

Existing productivity ledger snapshot observed on 2026-08-29:

- Human baseline: 120 minutes
- Human assisted time: 10 minutes
- Time returned: 110 minutes / 1.8333 hours
- Time reduction: 91.67%
- Speedup: 12.0x

This is the first formal productivity event in the ledger. Historical/legacy rows must be classified before they are included in the new `verified_human_hours_returned` field.

## Local-first AI routing snapshot

Latest 500-event routing sample observed on 2026-08-29:

- `local_vllm`: 493
- `local_model`: 7
- external calls recorded: 0
- total routing events: 500

Interpretation: 100% of this routing sample selected local execution and no external call was recorded. This is **not** equivalent to 500 successful tasks; individual local executions can fail and must retain their failure evidence.

The historical aggregate `local_calls` field is known to be inconsistent with runtime-level counts. Runtime-level counts are therefore the authoritative source for this snapshot until that aggregation bug is repaired.

## Self-healing metrics

New `self_heal_metrics` telemetry records:

- incident ID / cycle ID
- affected service and node
- detection time
- repair start and recovery time
- repair duration
- repair action and action result
- post-repair verification
- autonomous vs human intervention
- human intervention minutes
- manual recovery baseline and evidence class
- saved minutes / Human Hours Returned
- linked productivity event
- evidence references

### Anti-inflation rule

A successful autonomous repair **does not contribute any Human Hours Returned unless a service-specific manual recovery baseline exists**.

For example:

- repair succeeds and verifies, but no manual baseline exists → operational recovery is recorded, HHR = 0.
- measured manual baseline is 15 minutes, automatic repair verifies with 0 human minutes → 15 saved minutes / 0.25 HHR, marked verified only if the baseline itself is measured and verified.

False-DOWN corrections are state reconciliation events, not outages repaired, and must never be counted as repairs or human-time savings without evidence.

## Core project KPIs

1. Human Hours Returned
2. Verified Human Hours Returned
3. Productivity speedup
4. Human intervention rate
5. Autonomous completion rate
6. First-pass verification rate
7. Self-healing recovery rate
8. Mean Time to Recovery (MTTR)
9. Automatic verified recoveries
10. Failed recovery attempts
11. False-DOWN / stale-state corrections
12. Zero-progress cycles detected/suppressed
13. Duplicate work avoided
14. Local execution routing percentage
15. External model call percentage
16. External AI cost and estimated cost avoided
17. Cost per verified successful task
18. Cost per verified human hour returned
19. Integration Guardian verification rate
20. Rework rate

## Hackathon evidence policy

For the All Things Agentic Hackathon:

- simulated or degraded output never counts as PASS;
- routing to a model is not proof of successful execution;
- a generated file is not proof of integration;
- an automated repair is not proof of savings without a baseline;
- every demo claim should resolve to a correlation/task/incident ID, commit, test/log, cloud record or other reproducible evidence.

## Implementation added in branch `chatgpt/kpi-selfheal-20260829`

- `platform/inneros_core_runtime/productivity_metrics.py`
  - HHR, evidence class, verification and verified-HHR aggregation.
- `platform/inneros_core_runtime/self_heal_metrics.py`
  - service recovery baselines and auditable self-healing incident ledger.
- `platform/inneros_core_runtime/agents/ag42_service_guardian.py`
  - self-heal cycle IDs, timings and post-repair incident telemetry.
- `platform/tests/test_productivity_self_heal_metrics.py`
  - deterministic tests for measured HHR and the no-baseline/no-ROI rule.

## Verification state

- Python `compileall`: PASS for all changed/new Python files.
- Focused pytest: NOT VERIFIED in the isolated worktree because the system interpreter has no `pytest` module and creation of a project venv is approval-gated.
- The branch must not be presented as fully tested until the focused tests execute successfully in an approved project runtime.
