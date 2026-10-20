# Architecture — InnerOS Infrastructure Guardian

## 1. High-Level Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                    NEBIUS AI CLOUD                          │
│                                                             │
│       NVIDIA Open Models (Llama 3.1 70B / Nemotron)         │
│          ▲                                    │             │
│          │ Sanitized Telemetry                │ Structured  │
│          │ (No IPs, No Names, No Keys)        │ Diagnosis   │
│          │                                    ▼             │
└──────────┼────────────────────────────────────┼─────────────┘
           │                                    │
═══════════╪════════════════════════════════════╪══════════════
           │         LOCAL AIR-GAPPED BOUNDARY  │
═══════════╪════════════════════════════════════╪══════════════
           │                                    ▼
┌──────────┴───────────────┐        ┌─────────────────────────┐
│   Telemetry Sanitizer    │        │  Nebius/NVIDIA Adapter  │
└──────────────────────────┘        └───────────┬─────────────┘
                                                │
                                                ▼
                                    ┌─────────────────────────┐
                                    │ Local Fallback Model    │
                                    │ (Qwen3-30B-AWQ on AMD)  │
                                    └───────────┬─────────────┘
                                                │
                                                ▼
                                    ┌─────────────────────────┐
                                    │  InnerOS Policy Gate    │
                                    │ (Approval & Dry-Run)    │
                                    └───────────┬─────────────┘
                                                │
                                                ▼
                                    ┌─────────────────────────┐
                                    │   Capability Gateway    │
                                    │                         │
                                    │  • reboot.v1            │
                                    │  • poe_cycle.v1         │
                                    │  • verify_recovery.v1   │
                                    └───────────┬─────────────┘
                                                │
                       ┌────────────────────────┴────────────────────────┐
                       ▼                                                 ▼
            ┌─────────────────────┐                           ┌─────────────────────┐
            │    UniFi Adapter    │                           │ Grandstream Adapter │
            └──────────┬──────────┘                           └──────────┬──────────┘
                       │                                                 │
                       ▼                                                 ▼
            UniFi Enterprise APs                                Grandstream GWN
            & PoE Switches                                      Routers & APs
```

## 2. Security & Sovereignty Principles

1. **Zero Cloud Control Access:** Nebius AI Cloud does NOT hold network credentials, SSH keys, or direct network routes. It acts solely as an external reasoning consultant.
2. **Fail-Closed Policy Enforcement:** Every mutation (`network.device.reboot.v1`, `network.device.poe_cycle.v1`) is flagged with risk class `high` or `critical`. If invoked with `dry_run=False` without explicit owner approval, execution fails immediately with `approval_required`.
3. **Honest Provider Gaps:** Operations not supported by an upstream vendor (e.g. per-port PoE cycling on Grandstream GWN Cloud or unsupported third-party hardware) immediately return explicit `provider_gap` errors.
4. **Verifiable Receipts:** All executions emit cryptographic hashes ensuring tamper-evident operational history.
