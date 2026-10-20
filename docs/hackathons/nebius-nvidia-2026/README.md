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

1. **Cloud Intelligence:** Leverages open NVIDIA reasoning models (such as `meta-llama/Meta-Llama-3.1-70B-Instruct` or `nvidia/nemotron-4-340b-instruct`) hosted on **Nebius AI Cloud / Token Factory** to diagnose degraded physical systems from sanitized telemetry.
2. **Local Authority:** Nebius has zero direct network access or credentials to private equipment. All mutation plans pass through the **InnerOS Capability Gateway**, which enforces strict ownership policy, approval gating, and dry-run safety.
3. **Verified Physical Actions:** Every action is executed via governed local vendor adapters (UniFi, Grandstream GWN) and followed by automated post-action recovery verification, producing cryptographic evidence receipts for every operation.

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

If external cloud connectivity is degraded or external credits are restricted, the adapter transparently fails over to:
- Local AMD inference node running `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ` on `http://127.0.0.1:8000/v1`.
- Deterministic heuristic rules engine for mission-critical operations.

The local system remains 100% operational offline.
