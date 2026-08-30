# InnerOS Dual Deployment Runbook - 2026-08-30

Correlation: `inneros-dual-deployment-20260830`  
Task: `ops_6b04cbbfbe91`  
Scope: same InnerOS product across cloud and local/on-prem runtimes. No production deploy, no paid cloud resources, no UI/Auth work owned by Cursor.

## Topology

Cloud side:

- GCP project: `innerops-agentic-platform`
- Region: `us-central1`
- Cloud Run surface: `inneros.pcdoctor.ai`
- Current public routes:
  - `https://inneros.creatorcore.ai/app/login`
  - `https://workforce.creatorcore.ai/`
  - `https://inneros.pcdoctor.ai/`
  - `https://inneros.iskconguayaquil.org/app/login`

Local side:

- AMD node `.5`: AI inference, MCP ecosystem, local modules, local worker.
- Intel node `.4`: lightweight services, Ollama/fallback services, browser/review lanes when enabled.
- Canonical root: `/home/rlopez/inneros/inneros_core`
- Canonical platform: `/home/rlopez/inneros/inneros_core/platform`

## Active Local Runtime Inventory

Observed on AMD `.5`:

- `ralfia-mcp.service` - MCP ecosystem on `:8102`
- `ralfia-portal.service` - local control center on `:2002`
- `femar-mvp-core.service` - local Workforce shell on `:3010`
- `inneros-vllm-canary-rocm10.service` - ROCm10/vLLM on `:8000`
- `inneros-local-model-worker.service` - local model worker
- `ralfia-quoteops.service` - QuoteOps module
- `ralfia-smart-quoter.service` - Smart Quoter module on `:2026`
- `ralfia-founderos.service` - FounderOS on `:8766`
- `iskcon-desk.service` - ISKCON desk on `:2027`
- `vigilos-cursor.service` - Visitors backend on `:8011`
- `vigilos-cursor-frontend.service` - Visitors frontend on `:5175`

## Identity And Authorization Contract

The dual deployment must use one shared tenant/module entitlement model:

- Tenant membership decides which organization/entity a user can act for.
- Role decides what level of action is allowed.
- Module entitlement decides whether a module is visible and executable.
- Hidden navigation is not security. Backend/API calls must return 401/403 when unauthorized.
- Cloud login remains OAuth/managed where configured.
- Local degraded login is allowed only through an existing secure session or explicitly scoped local auth.

## Routing Contract

Default routing is local-first:

- Local model/coding/heavy reasoning: AMD `.5` ROCm/vLLM or local model worker.
- Lightweight services/fallback: Intel `.4` when available.
- Managed cloud services: GCP/Gemini/Cloud Run only when the task requires that capability.
- Cloud burst: explicit only, with cost and cleanup evidence.

MCP tools for agents:

- `inneros_dual_deployment_status` reports live topology and provider health.
- `inneros_dual_queue_operation` records a syncable operation with an idempotency key.
- `inneros_dual_reconcile_operations` marks queued operations reconciled in audit-only mode.
- `inneros_dual_deployment_drill` exercises cloud/local/degraded/reconcile without production deploys or shell access.

## Offline / Degraded Mode

Allowed when Internet/GCP is unavailable:

- Serve local health and control plane.
- Continue local MCP/RACB coordination.
- Route local AI tasks to AMD ROCm/vLLM or local worker.
- Queue syncable operations with idempotency keys.
- Read local cached/module-owned data when ownership is explicit.

Not allowed:

- Claim Firestore/GCP data is locally replicated without an explicit mirror.
- Open arbitrary shell or broad execution outside the Local Execution Plane allowlists.
- Auto-resolve destructive sync conflicts.
- Mark degraded/simulated output as PASS evidence.

## Sync / Reconciliation Contract

State sync must be idempotent and auditable:

- Every queued operation needs an idempotency key.
- Current queue collection: `inneros_dual_deployment_ops`.
- Every reconciled operation needs source, target, timestamp, actor, and outcome.
- Conflicts must be recorded before resolution.
- Destructive or customer-data conflict resolution needs owner-approved policy.
- Firestore/Mongo/current module stores remain source of truth only for the domains they already own.

## Verification Commands

Read-only dual deployment status:

```bash
cd /home/rlopez/inneros/inneros_core/worktrees/codex-module-rbac-audit-20260830
PYTHONPATH=platform /home/rlopez/inneros/inneros_core/platform/venv/bin/python3 -m pytest -q platform/tests/test_dual_deployment.py
PYTHONPATH=platform /home/rlopez/inneros/inneros_core/platform/venv/bin/python3 - <<'PY'
from inneros_core_runtime import dual_deployment
import json
print(json.dumps(dual_deployment.dual_deployment_status(probe_http=True, include_cloud=True), indent=2)[:8000])
print(json.dumps(dual_deployment.dual_deployment_drill(dry_run=False), indent=2)[:8000])
PY
```

MCP local runtime:

```bash
cd /home/rlopez/inneros/inneros_core/platform
PYTHONPATH=. ./venv/bin/python3 - <<'PY'
from inneros_core_runtime import mcp_server
import json
print(json.dumps(mcp_server.inneros_dual_deployment_status(probe_http=True, include_cloud=True), indent=2)[:8000])
print(json.dumps(mcp_server.inneros_dual_deployment_drill(dry_run=True), indent=2)[:8000])
PY
```

## Current Completion Boundary

This run creates the formal health/contract surface, queue, drill, tests and runbook. It does not:

- deploy production;
- create or spend cloud resources;
- modify Cursor's UI/Auth lane;
- duplicate databases;
- promise local availability for data that has no declared mirror.

The product UI can now wire real button/API events into `inneros_dual_queue_operation`.
