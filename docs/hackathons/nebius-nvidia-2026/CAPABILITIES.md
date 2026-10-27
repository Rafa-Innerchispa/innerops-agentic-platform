# Capabilities Specification — Physical AI Runtime

This document describes the three persistent capabilities added to the InnerOS Capability Gateway.

---

## 1. `network.device.reboot.v1`

- **Domain:** `network`
- **Mode:** `mutation`
- **Risk Class:** `high`
- **Required Scopes:** `ralfia:write`

### Parameters Schema:
```json
{
  "device_ref": "string (required) - IP, MAC, or device alias",
  "provider": "string - 'unifi' or 'grandstream_gwn'",
  "tenant_id": "string",
  "site_id": "string",
  "dry_run": "boolean (default: true)",
  "approval_token": "string (required if dry_run=false)",
  "owner_approval_ref": "string",
  "reason": "string"
}
```

### Invariants & Behaviors:
- When `dry_run=true`: Validates payload, inspects provider capabilities, stages the action plan, and returns `status: STAGED_DRY_RUN` with `mutation_applied: false`.
- When `dry_run=false` and unapproved: Returns `error: approval_required` and logs `status: BLOCKED_APPROVAL_REQUIRED`.
- An arbitrary non-empty token is not approval. The server context must mark owner approval as validated (or validate the candidate through an approval callback).
- Approval alone is insufficient: without a connected live provider executor the operation returns `provider_adapter_unavailable`; without a `REAL` provider receipt it returns `provider_receipt_required`.
- When `provider` is unsupported (e.g. `cisco`, `huawei`): Returns `error: provider_gap` listing supported providers.

---

## 2. `network.device.poe_cycle.v1`

- **Domain:** `network`
- **Mode:** `mutation`
- **Risk Class:** `critical`
- **Required Scopes:** `ralfia:write`

### Parameters Schema:
```json
{
  "switch_ref": "string (required) - Switch identifier or IP",
  "port": "integer (required) - Switch port number (1-48)",
  "provider": "string - 'unifi'",
  "tenant_id": "string",
  "site_id": "string",
  "dry_run": "boolean (default: true)",
  "approval_token": "string (required if dry_run=false)",
  "cycle_duration_seconds": "integer (default: 10)"
}
```

### Invariants & Behaviors:
- When requested on `grandstream_gwn`: Grandstream GWN Cloud does not expose per-port PoE cycling commands; the handler returns an honest `provider_gap` error explaining that power cycling must be triggered via an upstream managed switch (e.g. UniFi) or local PDU.
- When `dry_run=false` without approval: Fails closed with `error: approval_required`.
- When approved but no UniFi executor/receipt is connected: Fails closed; it never synthesizes `EXECUTED`.
- Emits evidence receipt including port number, switch reference, and execution hash.

---

## 3. `network.device.verify_recovery.v1`

- **Domain:** `network`
- **Mode:** `read_only`
- **Risk Class:** `low`
- **Required Scopes:** `ralfia:read`

### Parameters Schema:
```json
{
  "device_ref": "string (required) - Device IP or identifier to probe",
  "provider": "string",
  "expected_status": "string (default: 'online')",
  "max_wait_seconds": "integer (default: 30)",
  "mock_probe": "boolean (default: false)"
}
```

### Invariants & Behaviors:
- `mock_probe=true` produces `verification_mode: SIMULATED` and can never prove physical recovery.
- `mock_probe=false` requires a connected recovery probe; otherwise returns `provider_probe_unavailable` and `verification_mode: NOT_VERIFIED`.
- A connected probe returns `verification_mode: REAL` and its actual recovery state.
- Emits verification evidence receipt linked to the prior mutation.
