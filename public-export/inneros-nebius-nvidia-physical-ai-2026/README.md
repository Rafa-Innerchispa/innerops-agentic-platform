# InnerOS Infrastructure Guardian
### Physical AI Operator for Real-World Infrastructure
**Nebius × NVIDIA Global AI Hackathon 2026**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![NVIDIA Open Models](https://img.shields.io/badge/NVIDIA-Open_Models-76B900.svg)](https://build.nvidia.com)
[![Nebius AI Cloud](https://img.shields.io/badge/Nebius-AI_Cloud-00D4B2.svg)](https://nebius.ai)

> **Cloud intelligence. Local authority. Verified physical actions.**

---

## 💡 The Core Idea

Large Language Models are brilliant diagnosticians, but giving an external cloud AI direct SSH keys or write credentials to physical switches, APs, and power distribution units is dangerous.

**InnerOS Infrastructure Guardian** bridges this gap:
1. **Cloud Intelligence (Nebius + NVIDIA):** A model returned by the authenticated Nebius Token Factory catalog is selected only when its ID is explicitly NVIDIA/Nemotron. A provider receipt distinguishes real inference from the default local heuristic.
2. **Strict Trust Boundary & Sanitization:** Before leaving the building, private IPs, customer names, and MACs are sanitized. Nebius never receives direct control or credentials.
3. **Local Authority & Governed Execution:** All physical mutations (`network.device.reboot.v1`, `network.device.poe_cycle.v1`) are approval-gated. Live status is impossible without a connected provider adapter and a real provider receipt.
4. **Verified Physical Recovery:** A simulated probe is labeled `SIMULATED`; only a connected recovery probe can produce `verification_mode=REAL`.

---

## 🚀 Quickstart & Interactive Demo

Run the standalone demo in under 30 seconds:

```bash
# Clone the repository
git clone https://github.com/Rafa-Innerchispa/inneros-nebius-nvidia-physical-ai-2026.git
cd inneros-nebius-nvidia-physical-ai-2026

# Run the 7-stage Physical AI Workflow Demo
python3 src/demo_runner.py
```

The command above is intentionally reproducible without credentials or network access. Its output says `FAKE_INFERENCE_DRY_RUN_ACTION`, `physical_mutation_applied=false`, and `physical_recovery_verified=false`.

### Optional: authorized live Token Factory inference

First use authenticated `GET /v1/models` to select an available NVIDIA/Nemotron model. A live inference request requires an explicit credit gate:

```bash
export NEBIUS_API_KEY="your_nebius_api_key_here"
export NEBIUS_NVIDIA_MODEL="exact-model-id-returned-by-/models"
export NEBIUS_LIVE_SMOKE_AUTHORIZED=1
python3 src/demo_runner.py --live-inference
```

In the private InnerOS runtime, the key is read from `owner_vault`; it is never supplied as a CLI argument or printed. The public example accepts an environment variable only to remain standalone.

---

## 📐 The 7-Stage Physical AI Workflow

```text
1. Discover      ──> Inspect physical infrastructure state (read-only)
2. Diagnose      ──> Sanitize telemetry & analyze via Nebius × NVIDIA model
3. Recommend     ──> Suggest bounded operational action (reboot or PoE cycle)
4. Policy Gate   ──> Enforce OWNER_APPROVAL_REQUIRED (prevent unauthorized mutations)
5. Local Execute ──> Dispatch action via local UniFi or Grandstream adapter
6. Verify Recov  ──> Label simulated probes; require a real probe for a real claim
7. Evidence      ──> Issue tamper-evident cryptographic receipt
```

---

## 🛡️ Security & Privacy Model

- **No Secrets to Cloud:** Vendor API keys, SNMP community strings, and passwords never leave the local environment.
- **Anonymized Telemetry:** Private subnets (`192.168.x.x`) are transformed into documentation tokens (`10.0.0.x`).
- **Simulate by Default:** All capabilities support `dry_run=True` to stage and preview mutations before applying power cuts or reboots.
- **Honest Provider Gaps:** Operations not supported by upstream APIs (e.g. per-port PoE cycling on cloud-only routers) immediately return explicit `provider_gap` errors.

## Frontend API contract

The sanitized minimum contract is published in [`api-contract.json`](api-contract.json):

- `GET /api/guardian/overview`
- `POST /api/guardian/diagnose`
- `POST /api/guardian/actions/plan`
- `POST /api/guardian/recovery/verify`
- `GET /api/guardian/evidence/{id}`

The action endpoint is plan-only and forces `dry_run=true`. It does not expose live mutation credentials.

## Evidence taxonomy

| Label | Meaning |
|---|---|
| `REAL` | Provider response or real recovery probe produced a receipt |
| `SIMULATED` | Deterministic demo/dry-run; no physical effect |
| `BLOCKED` | Safety, adapter, model, credential, or authorization gate stopped execution |
| `NOT_RUN` | External provider was deliberately not contacted |

---

## 📜 License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

## Test the public export

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests -q
```

CI runs only offline tests and the dry-run demo; it never uses API keys or cloud credits. The five API routes describe the private integration contract; this standalone export does not expose a physical-control server.

## Verified API examples

See [sanitized HTTP responses](examples/api-http-evidence.json) from five actual requests to an isolated loopback ASGI runtime. This is API-contract evidence; it is not a public deployment, live Nebius inference, or physical-device recovery proof.
