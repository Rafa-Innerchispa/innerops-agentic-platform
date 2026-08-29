# Hyperloom MI325X Cloud Burst Runbook

InnerOS uses this lane only when local AMD R9700 capacity is not enough for a bounded workload and Rafael explicitly approves a temporary cloud burst.

## Canonical target

- Provider: DigitalOcean AMD Cloud Burst (`digitalocean-amd-cloud`)
- Region: `tor1`
- Size: `gpu-mi325x1-256gb`
- Image: `gpu-amd-base` (`AMD AI/ML Ready Image`)
- SSH key: `inneros-amd-5-id-ed25519`
- Default session cap: `8.00 USD`
- Hourly rate observed by API on 2026-08-29: `3.80 USD/hour`
- Billing stop rule: destroy the droplet; power-off is not accepted as completion evidence.

## MCP tools

- `digitalocean_hyperloom_mi325x_preflight`: read-only validation of token, region, size, image, SSH key and cost cap.
- `digitalocean_hyperloom_mi325x_session_plan`: builds the exact create payload and stays dry-run unless an `approval_id` and cloud apply window are active.
- `digitalocean_hyperloom_mi325x_bootstrap_script`: returns the reviewed bootstrap script for the temporary MI325X node. It contains no secrets.
- `digitalocean_hyperloom_mi325x_evidence_check`: refuses PASS unless real run evidence includes MI325X, SSH, Hyperloom version, workload result and destroy confirmation.

## Hyperloom requirements

Current pinned requirements come from AMD Hyperloom documentation:

- Supported GPUs: MI300X, MI325X, MI355X
- Target: MI325X
- OS: Ubuntu 22.04 or Ubuntu 24.04
- ROCm: 7.2.x
- Python: >=3.10
- Package: `hyperloom-inference-optimizer==1.0.0`
- Preferred mode: Docker/reproducible runtime

References:

- https://github.com/AMD-AGI/Hyperloom/blob/main/docs/install/install.md
- https://github.com/AMD-AGI/Hyperloom/blob/main/docs/compatibility.rst

## Safe execution sequence

1. Run `digitalocean_hyperloom_mi325x_preflight(spend_limit_usd=8.0)`.
2. Issue an approval with `cloud_approval_issue(provider="digitalocean-amd-cloud", action="hyperloom_mi325x_cloud_burst", project_id="inneros-hyperloom-mi325x", ttl_minutes=30)`.
3. Open the short apply window with `cloud_apply_window_set(provider="digitalocean-amd-cloud", project_id="inneros-hyperloom-mi325x", enabled=true, ttl_minutes=30, approval_id=...)`.
4. Run `digitalocean_hyperloom_mi325x_session_plan(approval_id=..., dry_run=false, spend_limit_usd=8.0)` to create the temporary node.
5. SSH into the droplet with the approved server key and run the script from `digitalocean_hyperloom_mi325x_bootstrap_script`.
6. Run one bounded InnerOS/Workforce smoke workload only. Capture command line, wall time, Hyperloom/runtime versions, GPU/VRAM metrics before/after, and result.
7. Destroy the droplet immediately with `digitalocean_destroy_droplet(droplet_id, approval_id=..., project_id="inneros-hyperloom-mi325x", dry_run=false)`.
8. Run `digitalocean_hyperloom_mi325x_evidence_check(evidence)` before closing the ops task.

## PASS policy

Preflight, dry-run payloads, probes and contracts are useful, but they are `PARTIAL`. `PASS` requires a real MI325X run plus destroy confirmation.
