# Verification Evidence — Nebius × NVIDIA Physical AI Runtime

**Correlation ID:** `nebius-nvidia-hackathon-20261019`  
**Task ID:** `ops_5541a2712440`  
**Work Branch:** `chatgpt/nebius-physical-ai-runtime-20261019`  
**Timestamp:** 2026-10-20T05:55:26Z  

---

## 1. Test Execution Summary

The test suite validates all required security, governance, and operational criteria:

```text
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/rlopez/inneros/inneros_core/var/local_execution/worktrees/Rafa-Innerchispa__innerops-agentic-platform/chatgpt__nebius-physical-ai-runtime-20261019
collected 44 items

platform/tests/test_nebius_nvidia_gateway.py ..................          [ 40%]
platform/tests/test_capability_gateway.py ........                       [ 59%]
tests/test_nebius_nvidia_runtime.py ..................                   [100%]

============================== 44 passed in 0.28s ==============================
```

---

## 2. Verified Capabilities & Invariants

| Invariant / Test | Capability / Component | Result | Detail |
|---|---|---|---|
| **Registration & Search** | `network.device.reboot.v1` | **PASS** | Discoverable via Capability Gateway |
| **Registration & Search** | `network.device.poe_cycle.v1` | **PASS** | Discoverable via Capability Gateway |
| **Registration & Search** | `network.device.verify_recovery.v1`| **PASS** | Discoverable via Capability Gateway |
| **Approval-Gating** | Live Reboot Mutation | **PASS** | `dry_run=False` blocked without approval (`approval_required`) |
| **Approval-Gating** | Live PoE Cycle Mutation | **PASS** | `dry_run=False` blocked without approval (`approval_required`) |
| **Approval-Granted** | Live Reboot Mutation | **PASS** | Dispatches cleanly when token provided |
| **Dry-Run Safety** | `network.device.reboot.v1` | **PASS** | Stages action plan (`mutation_applied=False`) |
| **Dry-Run Safety** | `network.device.poe_cycle.v1` | **PASS** | Stages port cycle (`mutation_applied=False`) |
| **Idempotency** | Capability Gateway Store | **PASS** | Same idempotency_key returns identical execution record |
| **Provider Gap** | GWN PoE Cycling | **PASS** | Returns honest `provider_gap` (GWN Cloud API limitation) |
| **Provider Gap** | Unsupported Vendor | **PASS** | Unsupported hardware returns `provider_gap` |
| **Post-Recovery Verification**| `network.device.verify_recovery.v1`| **PASS** | Validates ping reachability and port health |
| **Read-Only Preservation**| `network.device.query.v1` | **PASS** | Read-only discovery remains functional |
| **Telemetry Sanitizer**| `TelemetrySanitizer` | **PASS** | Redacts customer names, private IPs, and MACs |
| **Cloud AI Reasoning**| `NebiusNvidiaReasoning` | **PASS** | Formulates structured diagnosis and capability plan |
| **Local Model Fallback**| `NebiusNvidiaReasoning` | **PASS** | Transparent fallback when offline or without external key |
| **Bounded Workflow**| 7-Stage Physical AI Runner | **PASS** | End-to-end execution from discover to evidence receipt |

---

## 3. Reproducible Verification Command

```bash
python3 -m pytest platform/tests/test_nebius_nvidia_gateway.py platform/tests/test_capability_gateway.py tests/test_nebius_nvidia_runtime.py
```
