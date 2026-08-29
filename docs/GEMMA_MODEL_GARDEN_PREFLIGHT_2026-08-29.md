# Gemma Model Garden Preflight - 2026-08-29

## Result

Status: PARTIAL / DEPLOYABLE, NOT LIVE INFERENCE YET.

InnerOS can now query Vertex Model Garden from AMD using the installed Docker-based Google Cloud SDK wrapper when `--project` and `--billing-project` are both forced to `innerops-agentic-platform`.

The read-only preflight found deployable Gemma-family models without creating endpoints or spending GPU runtime.

## Command Evidence

```bash
/home/rlopez/.local/bin/gcloud ai model-garden models list \
  --model-filter=gemma \
  --limit=5 \
  --project=innerops-agentic-platform \
  --billing-project=innerops-agentic-platform \
  --format=json
```

Observed result:

- `publishers/google/models/functiongemma`, version `function-gemma-270m`, GA, deployable.
- Cheapest useful deployment option observed: `g2-standard-12` with `NVIDIA_L4`, 1 accelerator, predict route `/generate`.
- `publishers/google/models/gemma`, versions including `gemma-1.1-2b-it`, deployable but experimental.

No endpoint was deployed during this preflight.

## Live Smoke Evidence

The following bounded low-cost lanes responded live:

- `google-gemini-35-bounded-review`: `gemini-3.5-flash-lite`, Vertex global, text response `ok`.
- `google-flash-lite-triage`: `gemini-2.5-flash-lite`, `us-central1`, text response `ok`.
- `google-memory-embedding`: `gemini-embedding-001`, `us-central1`, 3072 dimensions.

The serverless Gemma lane remains unavailable:

- `google-gemma-bounded-review`: `gemma-3-27b-it`, `us-central1`, `404 NOT_FOUND` from Vertex publisher model path.

## Tooling Added

- `google_model_garden_gemma_preflight`: read-only MCP tool for ChatGPT/local agents.
- Forces `--project` and `--billing-project` to avoid ADC quota-project ambiguity.
- Uses a configurable `INNEROS_GCLOUD_TIMEOUT_SECONDS`, default `30`, to avoid false timeout failures on token refresh.
- Does not deploy resources. Endpoint deployment must be a separate explicit action with cost guard and cleanup.

## Next Step For Live Gemma PASS

To claim Gemma live PASS, run a separate approved deploy cycle:

1. Deploy `function-gemma-270m` or lowest-cost supported Gemma option to Vertex AI endpoint.
2. Invoke `/generate` with a bounded ARIA routing/triage payload.
3. Persist endpoint name, model/version, region, request correlation ID, response hash/summary and timestamp.
4. Destroy or scale down the endpoint immediately unless needed for recording.
5. Record actual/estimated cost.

Until then, Gemma status remains PARTIAL, not PASS.
