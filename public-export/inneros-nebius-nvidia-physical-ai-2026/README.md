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
1. **Cloud Intelligence (Nebius + NVIDIA):** Open NVIDIA reasoning models running on **Nebius Token Factory / AI Cloud** analyze sanitized telemetry to diagnose hardware degradation (buffer saturation, PoE voltage drops, silent packet storms).
2. **Strict Air-Gap & Sanitization:** Before leaving the building, private IPs, customer names, and MACs are sanitized. Nebius never receives direct control or credentials.
3. **Local Authority & Governed Execution:** All physical mutations (`network.device.reboot.v1`, `network.device.poe_cycle.v1`) are strictly approval-gated and executed by the local node via vendor adapters (UniFi, Grandstream GWN).
4. **Verified Physical Recovery:** The local engine performs post-reboot latency, ARP, and connectivity probes to confirm restoration and produces cryptographic audit receipts.

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

### Optional: Connect to Live Nebius AI Cloud

Set your Nebius Token Factory API key to use live NVIDIA models (`meta-llama/Meta-Llama-3.1-70B-Instruct`):

```bash
export NEBIUS_API_KEY="your_nebius_api_key_here"
python3 src/demo_runner.py
```

*(Note: When no API key is provided, the demo automatically engages the resilient local model fallback).*

---

## 📐 The 7-Stage Physical AI Workflow

```text
1. Discover      ──> Inspect physical infrastructure state (read-only)
2. Diagnose      ──> Sanitize telemetry & analyze via Nebius × NVIDIA model
3. Recommend     ──> Suggest bounded operational action (reboot or PoE cycle)
4. Policy Gate   ──> Enforce OWNER_APPROVAL_REQUIRED (prevent unauthorized mutations)
5. Local Execute ──> Dispatch action via local UniFi or Grandstream adapter
6. Verify Recov  ──> Test ICMP reachability and port telemetry
7. Evidence      ──> Issue tamper-evident cryptographic receipt
```

---

## 🛡️ Security & Privacy Model

- **No Secrets to Cloud:** Vendor API keys, SNMP community strings, and passwords never leave the local environment.
- **Anonymized Telemetry:** Private subnets (`192.168.x.x`) are transformed into documentation tokens (`10.0.0.x`).
- **Simulate by Default:** All capabilities support `dry_run=True` to stage and preview mutations before applying power cuts or reboots.
- **Honest Provider Gaps:** Operations not supported by upstream APIs (e.g. per-port PoE cycling on cloud-only routers) immediately return explicit `provider_gap` errors.

---

## 📜 License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
