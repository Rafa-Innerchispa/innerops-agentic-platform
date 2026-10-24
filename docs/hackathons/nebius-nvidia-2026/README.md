# InnerOS Infrastructure Guardian — Nebius × NVIDIA Global AI Hackathon 2026

**Track:** Physical AI / Infrastructure Agents  
**Thesis:** *Cloud intelligence. Local authority. Verified physical actions.*  
**Target Repository:** `Rafa-Innerchispa/inneros-nebius-nvidia-physical-ai-2026`  
**Runtime Workspace:** `Rafa-Innerchispa/innerops-agentic-platform`  
**Correlation ID:** `nebius-nvidia-hackathon-20261019`  

---

## 1. Executive Summary

**InnerOS Infrastructure Guardian** is a governed Physical AI operator for physical building and network infrastructure (switches, routers, enterprise Wi-Fi APs, and PoE equipment).

Traditional infrastructure monitoring either relies on dumb static rules or risks cloud agents executing arbitrary remote shell commands on private internal networks. **InnerOS Infrastructure Guardian** solves this through a strictly partitioned architecture:

1. **Cloud Intelligence:** Uses the current Nebius Token Factory OpenAI-compatible API. Live mode first checks authenticated `GET /models` and only selects an ID explicitly identified as NVIDIA/Nemotron; no hard-coded historical model is presented as current proof.
2. **Local Authority:** Nebius has zero direct network access or credentials to private equipment. All mutation plans pass through the **InnerOS Capability Gateway**, which enforces strict ownership policy, approval gating, and dry-run safety.
3. **Verified Physical Actions:** An action is `REAL` only when a connected vendor adapter returns a provider receipt. A recovery is `REAL` only when a connected probe confirms it. Dry-run and mock probes remain useful but are labeled `SIMULATED`.

---

## 2. Key Technical Capabilities

The InnerOS Capability Gateway registers three persistent physical operations:

| Capability ID | Mode | Risk Class | Description | Gating |
|---|---|---|---|---|
| `network.device.reboot.v1` | Mutation | High | Governed reboot of APs, routers, and switches | Owner Approval Required for live |
| `network.device.poe_cycle.v1` | Mutation | Critical | Per-port PoE power cycle to hard-reset hung hardware | Owner Approval Required for live |
| `network.device.verify_recovery.v1` | Read-Only | Low | Post-mutation connectivity and health verification | Read-Only Scoped |

Existing read-only telemetry capabilities (`network.device.query.v1`) remain intact and unchanged.

---

## 3. The Bounded 7-Stage Physical AI Workflow

```text
[1. Discover]      -> Query live infrastructure via Device Fabric (read-only)
        │
[2. Diagnose]      -> Sanitize telemetry & analyze via Nebius × NVIDIA open model
        │
[3. Recommend]     -> Formulate structured recommendation & required capability
        │
[4. Policy Gate]   -> Enforce OWNER_APPROVAL_REQUIRED (block unapproved live mutations)
        │
[5. Local Execute] -> Dispatch approved action via local UniFi or Grandstream adapter
        │
[6. Verify Recov]  -> Validate ping, latency, and telemetry return to 'online'
        │
[7. Receipt]       -> Emit immutable audit receipt with cryptographic hash
```

---

## 4. Privacy & Sanitization Invariant

Before any telemetry is forwarded to the Nebius cloud endpoint, the **`TelemetrySanitizer`** pipeline:
- Anonymizes customer, site, and building names.
- Replaces internal IPv4 subnets (e.g. `192.168.x.x`) with synthetic documentation tokens (`10.0.0.x`).
- Masks physical MAC addresses and device serial numbers.
- Strips all authentication tokens, credentials, and passwords.

Private network credentials **never leave the local node**.

---

## 5. Resilient Local Fallback

If external cloud connectivity is degraded or external credits are restricted, this branch uses a deterministic local heuristic and labels the result `LOCAL_HEURISTIC`. It does **not** claim that a local Qwen model ran unless a separate local inference receipt proves it.

The local system remains 100% operational offline.

---

## 6. Frontend API Contract

The runtime mounts a sanitized, plan-only contract:

- `GET /api/guardian/overview`
- `POST /api/guardian/diagnose`
- `POST /api/guardian/actions/plan`
- `POST /api/guardian/recovery/verify`
- `GET /api/guardian/evidence/{id}`

The frontend cannot submit approval credentials or invoke a live mutation through these routes. See `public-export/inneros-nebius-nvidia-physical-ai-2026/api-contract.json` and `VERIFICATION_EVIDENCE.md`.
