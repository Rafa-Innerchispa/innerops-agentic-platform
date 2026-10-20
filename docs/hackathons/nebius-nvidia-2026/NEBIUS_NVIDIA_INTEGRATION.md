# Nebius × NVIDIA Integration Guide — InnerOS Infrastructure Guardian

## 1. Overview

InnerOS integrates open NVIDIA models hosted on **Nebius AI Cloud / Token Factory** as the high-level reasoning intelligence of the physical infrastructure operator.

Supported Models:
- `meta-llama/Meta-Llama-3.1-70B-Instruct`
- `nvidia/nemotron-4-340b-instruct`
- `meta-llama/Meta-Llama-3.1-8B-Instruct`

Endpoint compatibility:
Standard OpenAI-compatible Chat Completions API (`https://api.studio.nebius.ai/v1/chat/completions`).

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

If `NEBIUS_API_KEY` is omitted or network connectivity to Nebius AI Cloud is interrupted:
1. `NebiusNvidiaReasoning` flags `fallback_engaged = true`.
2. Diagnosis and recommendation are computed locally on AMD hardware using `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ` on `http://127.0.0.1:8000/v1` or deterministic physical heuristic rules.
3. The workflow completes without interruption or paid external consumption.
