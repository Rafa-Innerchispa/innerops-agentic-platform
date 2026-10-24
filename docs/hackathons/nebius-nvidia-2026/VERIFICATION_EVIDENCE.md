# Verification Evidence — Nebius × NVIDIA Physical AI Runtime

**Correlation ID:** `nebius-nvidia-hackathon-20261024`

**Source branch:** `chatgpt/nebius-physical-ai-runtime-20261019` at `a69908d57cc40a45ae927ab13c279a209387e224`

**Validation branch:** `codex/nebius-nvidia-validation-20261024`

**Validation date:** 2026-10-24

## Reproducible test result

```text
python -m pytest \
  platform/tests/test_capability_gateway.py \
  platform/tests/test_nebius_nvidia_gateway.py \
  tests/test_nebius_nvidia_runtime.py \
  platform/tests/test_guardian_api_contract.py \
  public-export/inneros-nebius-nvidia-physical-ai-2026/tests/test_public_runtime.py -q

.........................................................                [100%]
57 passed, 1 warning in 12.77s
```

The warning is a Starlette notice about the future `httpx2` TestClient migration; it does not affect the assertions.

## Evidence classification

| Item | Result | Evidence mode | Meaning |
|---|---|---|---|
| Token Factory base URL | PASS | DOCUMENTED | Current official URL is `https://api.tokenfactory.nebius.com/v1` |
| NVIDIA model selection | PASS | MOCKED/CONTRACT | Code validates an NVIDIA/Nemotron ID against authenticated `/models` before live use |
| Billable Nebius inference | NOT RUN | BLOCKED | No explicit credit authorization was available; no external request was sent |
| Default reasoning demo | PASS | LOCAL_HEURISTIC | Deterministic offline result, explicitly not an LLM claim |
| Reboot / PoE plan | PASS | SIMULATED | Dry-run, `mutation_applied=false` |
| Approved action without adapter | PASS | BLOCKED | `provider_adapter_unavailable`; no synthetic execution |
| Live adapter response without receipt | PASS | BLOCKED | `provider_receipt_required` |
| Recovery mock | PASS | SIMULATED | Cannot be promoted to physical recovery proof |
| Recovery without real probe | PASS | BLOCKED | `provider_probe_unavailable` and `NOT_VERIFIED` |
| Idempotency | PASS | TESTED | Reused idempotency key returns the same execution and evidence hash |
| Telemetry sanitization | PASS | TESTED | Private IPs, MACs, tokens, passwords, and serial values removed |
| Frontend contract | PASS | TESTED | Five `/api/guardian` routes mounted in the runtime app |
| Public Apache-2.0 license | PASS | VERIFIED | Public export contains the complete OSI-approved license text |

## Local smoke receipt

```bash
python3 platform/scripts/smoke_nebius_nvidia.py
```

Expected truth labels:

```json
{
  "mode": "FAKE",
  "external_inference": {"status": "BLOCKED_NOT_AUTHORIZED"},
  "secret_printed": false
}
```

## Authorized live smoke (not executed in this validation)

```bash
NEBIUS_LIVE_SMOKE_AUTHORIZED=1 \
python3 platform/scripts/smoke_nebius_nvidia.py --live
```

Requirements:

1. `owner_vault:nebius_token_factory/api_key` or `owner_vault:nebius/api_key` exists.
2. The account has owner-authorized quota/credit.
3. Authenticated `/models` returns an NVIDIA/Nemotron model.

The script has no raw-key argument and never prints the secret. Only a successful Token Factory response produces `evidence_mode=REAL` with response metadata and a SHA-256 receipt.

## Sanitized frontend contract

- `GET /api/guardian/overview`
- `POST /api/guardian/diagnose`
- `POST /api/guardian/actions/plan`
- `POST /api/guardian/recovery/verify`
- `GET /api/guardian/evidence/{id}`

`actions/plan` forcibly removes approval material and sets `dry_run=true`; live mutation remains outside this frontend contract.
