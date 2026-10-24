# Nebius × NVIDIA Integration Guide — InnerOS Infrastructure Guardian

## 1. Overview

InnerOS integrates open NVIDIA models hosted on **Nebius AI Cloud / Token Factory** as the high-level reasoning intelligence of the physical infrastructure operator.

Model validation:
- Query authenticated `GET https://api.tokenfactory.nebius.com/v1/models` at runtime.
- Accept only a configured model present in that response whose ID is explicitly NVIDIA/Nemotron.
- Do not claim a model is currently hosted from a historical model name or unauthenticated documentation alone.

Endpoint compatibility:
Standard OpenAI-compatible Chat Completions API (`https://api.tokenfactory.nebius.com/v1/chat/completions`).

Primary references checked on 2026-10-24:
- Nebius Token Factory quickstart: <https://docs.tokenfactory.nebius.com/quickstart>
- Switching an OpenAI-compatible client: <https://docs.tokenfactory.nebius.com/switch>
- Live model-list API example: <https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models>
- NVIDIA Nemotron model card: <https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/modelcard>

---

## 2. Privacy & Air-Gap Model

Nebius is an advisory reasoning layer, **NOT an administrative control plane**.

### The Sanitization Pipeline (`TelemetrySanitizer`):
```text
Raw Internal Telemetry                    Sanitized Cloud Payload
┌───────────────────────────────┐        ┌───────────────────────────────┐
│ Site: Torre Bellini Tower     │  ───>  │ Site: Site-Alpha-01           │
│ Device: 192.168.3.15          │        │ Device: 10.0.0.1              │
│ MAC: 00:1A:2B:3C:4D:5E        │        │ MAC: 02:00:00:00:00:01        │
│ Auth: Bearer gwn_sec_token_99 │        │ Auth: [STRIPPED]              │
└───────────────────────────────┘        └───────────────────────────────┘
```

The cloud engine analyzes patterns (e.g. latency spikes, memory utilization bloat, PoE voltage drops) without exposing the identity, geography, or private IP addresses of real facilities.

---

## 3. Local Model Fallback

If the server-side vault key is absent, credit use is not explicitly authorized, the model is absent from the live catalog, or connectivity fails:
1. `NebiusNvidiaReasoning` flags `fallback_engaged = true`.
2. Diagnosis and recommendation use `deterministic_inneros_heuristic_v1` and are labeled `LOCAL_HEURISTIC`.
3. The workflow completes without interruption or paid external consumption.

## 4. Reproducible smoke modes

```bash
# Default: no network, no key, no credits
python3 platform/scripts/smoke_nebius_nvidia.py

# Live: requires owner_vault key plus explicit cost authorization
NEBIUS_LIVE_SMOKE_AUTHORIZED=1 python3 platform/scripts/smoke_nebius_nvidia.py --live
```

The live script never accepts a raw key argument and never prints secret material.
