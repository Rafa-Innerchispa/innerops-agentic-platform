# Gemma Model Garden Live Evidence - 2026-08-29

## Result

Status: PASS for a bounded live FunctionGemma inference through Vertex Model Garden.

InnerOS can query Vertex Model Garden from AMD using the installed Docker-based Google Cloud SDK wrapper when `--project` and `--billing-project` are both forced to `innerops-agentic-platform`.

The read-only preflight found deployable Gemma-family models without creating endpoints. A later bounded deploy cycle created FunctionGemma 270M, ran one inference, then removed serving resources.

## Preflight Command Evidence

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

## Live FunctionGemma Cycle

Deploy command used the lowest practical observed GPU option:

```bash
gcloud ai model-garden models deploy \
  --model=google/functiongemma@function-gemma-270m \
  --region=us-central1 \
  --project=innerops-agentic-platform \
  --billing-project=innerops-agentic-platform \
  --machine-type=g2-standard-12 \
  --accelerator-type=NVIDIA_L4 \
  --accelerator-count=1 \
  --disable-dedicated-endpoint \
  --endpoint-display-name=inneros-functiongemma-270m-ondemand-20260829 \
  --accept-eula \
  --quiet
```

Evidence:

- operation: `2882646555741913088`
- endpoint: `projects/718088522103/locations/us-central1/endpoints/mg-endpoint-e6bc84df-58a9-4862-a283-ae5ce083d1df`
- model: `projects/718088522103/locations/us-central1/models/4933421262656503808@1`
- deployed model id: `8522829748089389056`
- publisher model: `publishers/google/models/functiongemma@function-gemma-270m`

The first Spot attempt did not create a live model because `CustomModelServingPreemptibleCPUsPerProjectPerRegion` quota was exceeded. The on-demand L4 attempt succeeded.

## Inference Evidence

Request correlation: `allthingsagentic-gemma-live-20260829`

A bounded `gcloud ai endpoints predict` call returned a live prediction from the deployed FunctionGemma model.

- response hash: `b191145dd78301589809c1e2c477d9d28b2474ff4aa945e5ffb0168e1a2a497e`
- response preview: `The analysis of the correlation between inner`
- evidence JSON: `platform/docs/evidence/functiongemma_live_2026-08-29.json`

The chatCompletions request format returned a Google container-side 500 (`ChatCompletionRequest is not defined`), so the successful proof used the simple prompt format accepted by this deployment.

## Cleanup

Cleanup completed immediately after the proof:

- undeploy deployed model: PASS
- delete endpoint: PASS
- delete imported Vertex model: PASS
- post-cleanup `inneros-functiongemma` endpoints: `[]`
- post-cleanup `functiongemma` models: `[]`

No FunctionGemma endpoint/model remained active after the test.

## Reusable Tooling Added

- `google_model_garden_gemma_preflight`: read-only MCP tool for ChatGPT/local agents.
- Forces `--project` and `--billing-project` to avoid ADC quota-project ambiguity.
- Uses configurable `INNEROS_GCLOUD_TIMEOUT_SECONDS`, default `30`, to avoid false timeout failures on token refresh.
- Does not deploy resources; deployment remains a separate explicit cost-bearing action.
