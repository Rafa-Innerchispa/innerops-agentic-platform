# Execution resource audit, 2026-10-29 (America/Guayaquil)

Incident reference: `ops_7039e9cc4f11`. The owner requested protection across
external agents and local GPU workloads after repeated Cursor credit consumption.

## Findings

1. CRITICAL: Intel was executing an older Cursor autopilot than main. Its
   dispatcher could retry failed and verification tasks after supersession.
   Containment and the first repair are in PR #249; Cursor remains paused.
2. HIGH: Temporal activity retries were bounded at three, but independent
   dispatchers could start new executions outside that counter.
3. HIGH: the existing external credit governor counted repair-run records.
   Direct SDK launches could bypass that accounting. Its limits are counts,
   not verified currency or provider token balances.
4. HIGH: capacity classification recommends concurrency but does not itself
   enforce mutual exclusion at every model request boundary.
5. HIGH: two regression fixtures reached the live Temporal/Mongo task queue,
   causing repeated approval emails. Those tasks were quarantined earlier.
6. Notification gap: both Evolution WhatsApp sessions were disconnected. HA
   accepted initial push requests but handset display was not verified; expired
   approval requests subsequently fell back to email.
7. The inspected `activity_execute_agent_graph` executes existing bounded
   Python logic; its description mentioning LangGraph is not evidence of a live
   StateGraph. Adding a graph framework would not fix out-of-band admission.

## Implemented controls

Extend existing executors with a shared resource admission guard backed by the
existing task and coordination-state collections. No second scheduler or queue.

- Cursor SDK/cloud dispatch, Codex/Antigravity bounded execution, local Dev Swarm
  generic execution and the Temporal agent activity reserve before execution.
- Maximum three execution reservations per task, shared across provider changes
  and process restarts. A successful result cannot be resubmitted by rerunning.
- Atomic task mutex; a crashed worker leaves its mutex locked for investigation.
- External reservations also consume atomic daily/monthly allowances using the
  existing credit governor's configured limits. Reservations are conservative:
  partial failures do not refund counts automatically. Periods are UTC calendar
  day/month, and this new counter is prospective, not recovered historic billing.
- Maximum 1,800 accumulated task seconds is checked at admission. In-flight work
  remains bounded by the executor's existing timeouts; this is not an exact
  per-millisecond kill switch or an invoice cap.
- Task-bound local inference has a twelve-request budget. The router admits four
  cluster-wide concurrent `run_local_model` calls using expiring Mongo leases.
  There is no busy-wait when capacity is exhausted, and shared model services are
  not killed to free capacity. Lease expiration recovers abandoned reservations;
  it is not proof of cancellation inside the model server.
- Tests cannot admit live workflows through `start_task_workflow` while pytest
  is running. Tests needing admission behavior must mock that boundary.
- Local coding tasks with no repo/project hints are rejected before admission.
- A deterministic minute-by-minute auditor records superseded active tasks,
  exhausted budgets and overlong executions. It does not call an LLM or kill
  unrelated processes. HA alert retries are capped at three for unchanged findings.
- The auditor checks that all five executor/router guard hooks remain in source.
  Missing hooks latch the shared circuit closed and stop the known automatic
  dispatch launchers. Restoring source does not silently clear that latch.

## Coverage and limits

These protections apply to the named InnerOS entrypoints. Direct IDE sessions,
direct HTTP clients to vLLM/Ollama, raw provider API calls, cloud infrastructure
billing and SDK-internal tool/model loops are not universally intercepted here.
Other agents' SDK-internal calls can exceed one billable call per reservation.
Do not call these counters a dollar spending cap. Independent provider-side
billing caps and reconciliation of actual usage remain necessary.

GPU leases bound router admission, not VRAM reservation or temperature. The
existing capacity governor and runtime timeouts are retained. A process that
bypasses the router is an audit coverage gap, not a certified safe path.

Runtime activation must preserve unrelated node differences. Deploy only the
new guard/auditor and the small import/decorator/admission hunks; retain backups.
Long-lived workers need a controlled reload before they can use changed imports.
Do not automatically reactivate Cursor when deploying this repair.

## Validation

Final focused repository suite: 181 passed, five subtests passed. Effective
Intel runtime: 68 passed. Effective AMD runtime: 68 passed. The shared guard and
auditor sources match on both hosts. Intel's central audit timer is active and
its initial report has no findings among the four currently active tasks.
Temporal had nine running workflows but zero pending activities before the
controlled worker reload. Intel MCP/profiles and orchestration services were
reloaded and checked active; Cursor's automatic timer remained inactive.

Status: LIVE for these guarded runtime entrypoints and central audit;
PARTIAL for infrastructure-wide certification due to the direct-client,
provider-billing and notification-delivery limitations stated below/above.
The minute-by-minute observer is central on Intel; its HA/failover certification
is not claimed. Both nodes independently enforce the shared resource ledger.

Tests use in-memory Mongo (`mongomock`), mocked transports and no model requests.
They exercise parallel admission, cross-provider retry accounting, successful
submission dedupe, cumulative wall budget, local concurrency, twelve-call budget,
async Temporal registration, cancelled-task rejection at actual entrypoints,
provider allowances, fixture isolation and bounded notification retries.

Official references:
- https://docs.temporal.io/design-patterns/fixed-count-retries
- https://docs.langchain.com/oss/python/langgraph/graph-api

Temporal caps attempts within an activity; LangGraph limits steps within a graph.
Neither automatically imposes a global budget on an independent dispatcher.
