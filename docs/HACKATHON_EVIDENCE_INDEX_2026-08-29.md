# InnerOS / ARIA — Hackathon Evidence Index — 2026-08-29

This index exists so judges, reviewers and future maintainers can distinguish **source integration**, **live operational evidence**, **historical live evidence**, **measured KPI evidence**, and **still-open final verification gates**.

InnerOS does not count simulated, degraded, scaffold-only or unexecuted work as PASS.

## Canonical repository state

Repository: `Rafa-Innerchispa/innerops-agentic-platform`

Key canonical merges during final hardening:

- `8cad655329184fe15269965476a11e19b25e7cdf` — Google Gemini 3.5 / governed runtime source integration.
- `8ec4dc0bb9cf8af2d8e677276caea5df9e6d4708` — Google hackathon compliance matrix.
- `35942960725c70fb4ea55d59364a7f65eeeb7d67` — auditable KPI/ROI + self-healing incident source integration.
- `b431968f59781092cdd5057806e8b0f28cf8cce0` — Gemini 3.5 Flash model endpoint corrected from `us` to `global` based on current Google Enterprise/GenAI guidance.

## Google mandatory stack

Fresh Devpost rule check on 2026-08-29 shows Gemini 3.5+ is mandatory.

Canonical source now targets:

- Gemini 3.5 Flash (`gemini-3.5-flash`)
- Google GenAI SDK
- Google ADK / A2A integration contracts
- Vertex / Google managed inference path
- Cloud Run
- Firestore
- Pub/Sub
- Memory Bank/state synchronization
- Model Armor
- dedicated least-privilege runtime identity
- correlation/tracking envelope
- OpenTelemetry / Cloud Logging evidence path
- bounded InnerOS tools / Agent Gateway pattern

See `docs/GOOGLE_HACKATHON_COMPLIANCE_2026-08-29.md` for the exact SOURCE vs LIVE matrix and final E2E gate.

### Historical real Gemini 3.5 evidence

An Antigravity hardening run on 2026-08-28 reported a real Vertex `generateContent` HTTP 200 using Gemini 3.5 Flash, with Firestore evidence:

- correlation: `hackathon-demo-first-class-governance`
- Firestore evidence id: `ev_hackathon-demo-first-class-governance_gen-20260828045546`
- synchronized state: `inneros_memory_bank`

This is historical LIVE evidence. The final submission gate requires a refreshed run on current canonical code and does not silently substitute this historical proof for current deployment verification.

### Latest previously validated full Google E2E

A later integration E2E validated the complete Google evidence path using Gemini 2.5 Flash, including Firestore, Pub/Sub, logging/memory and live Model Armor behavior. Because the hackathon now explicitly requires Gemini 3.5+, that run is useful architectural evidence but is **not sufficient for final model eligibility**.

The final current-canonical gate is therefore:

`Gemini 3.5+ LIVE -> Model Armor -> bounded real tool -> persistent state -> Pub/Sub -> correlated logs/trace -> independent verification`

No simulation or degraded fallback can satisfy this gate.

## A2A / agent fabric evidence

Verified operational architecture includes:

- 55 functional catalog agents
- 5 special control/execution cards
- 60 A2A Agent Cards total in the verified runtime
- AG-25 root orchestrator
- canonical registry projected into Agent Cards
- durable RACB/Mongo lifecycle
- delivery != execution semantics
- IDE Task Bridge
- Cursor ACP capability path
- verified Codex adapter
- local Dev Swarm worktrees
- independent Integration Guardian

A2A repair evidence is durable in the ops task `ops_8f4a62a8a8fd` and canonical merge `c7092ec582d60ac20fbc6f17ced19740dac0ecc2`.

## MCP / bounded capability surface

Live MCP readback on 2026-08-29:

- server: 3.5.0
- catalog: 2.68.0
- runtime tool count: 603
- catalog tool count: 603
- catalog guard: `catalog_expanded`
- `tool_loss_detected=false`

The large tool surface is not handed wholesale to every model. MCP profiles, scopes, bounded tools, approval gates and agent capabilities control exposure.

## Local-first compute evidence

Latest 500 routing-event sample on 2026-08-29:

- `local_vllm`: 493
- `local_model`: 7
- external calls recorded: 0
- total sampled routing events: 500

This means 100% of the sampled routing decisions used local runtimes and 0 external calls were recorded. It does **not** mean 500 tasks succeeded; failures remain visible and must not be relabeled as successful work.

The aggregate `local_calls` counter is known to undercount relative to runtime-level records. `runtime_counts` is the authoritative field for this snapshot until that aggregation defect is fixed.

## Human Hours Returned / productivity evidence

First formal productivity baseline currently recorded:

- manual/human baseline: 120 min
- assisted human time: 10 min
- time returned: 110 min
- Human Hours Returned: 1.8333 h
- time reduction: 91.67%
- speedup: 12.0x

The KPI hardening added evidence classes (`measured`, `estimated`, `inferred`, `manual`) and a separate `verified_human_hours_returned` concept so estimated values cannot be presented as directly measured results.

See `docs/KPI_ROI_EVIDENCE_2026-08-29.md`.

## Self-healing ROI evidence

Canonical source now includes a dedicated self-healing incident ledger that can record:

- incident/cycle id
- affected service/node
- detection and recovery timestamps
- repair action and duration
- post-repair verification
- autonomous vs human intervention
- human intervention minutes
- manual recovery baseline and evidence class
- Human Hours Returned
- linked productivity event/evidence references

Core anti-inflation rule:

> A verified automatic repair without a documented manual recovery baseline records operational recovery but contributes **0 Human Hours Returned**.

False-DOWN state reconciliation is not counted as an outage repaired.

MCP read/write tools for the new self-heal ledger are a final integration gate. Existing productivity tools are already live.

## Current live local AI / AMD truth

Local Qwen3-Coder inference is operational on the AMD Radeon AI PRO R9700.

Do not conflate the ROCm10 migration lane name with the active vLLM serving runtime. Evidence has shown both a ROCm10 isolated stack and an active vLLM runtime that has at times still reported ROCm/HIP 7.14. Final public claims should use runtime readback, not container names.

## Evidence policy

A public PASS requires the relevant evidence class:

- source claim -> commit / diff / code path
- test claim -> executed test output
- runtime claim -> live status/readback
- cloud claim -> cloud revision/log/state evidence
- self-heal claim -> incident + verification
- ROI claim -> baseline + actual assisted time + evidence class
- integration claim -> one correlated E2E path, not merely separate component health checks

InnerOS deliberately preserves FAIL/PARTIAL/BLOCKED states. This is part of the system's trust model, not a presentation defect.
