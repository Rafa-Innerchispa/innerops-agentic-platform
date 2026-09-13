# AG-32 UniFi / Wi-Fi Operations

AG-32 now treats UniFi/Wi-Fi requests as an operational workflow instead of falling through to the generic Home Ops digest.

## Contract

`observe -> diagnose -> bounded action -> verify`

For UniFi requests AG-32 reads the Home Assistant UniFi integration, inventories APs, gateways and WLANs, checks AP state/uptime/resource telemetry when exposed, counts clients by WLAN, and reports findings, evidence, likely causes, before/after state, limitations and approval-gated next actions.

The current Home Assistant integration does not expose complete RF telemetry such as channel utilization, retry rate, per-client RSSI, transmit power or interference. AG-32 therefore fails closed for channel/power/firmware/password/AP-restart changes until an audited UniFi controller adapter with rollback evidence is available.

## Safety

- No password regeneration.
- No SSID shutdown.
- No firmware update.
- No AP/gateway restart from a generic repair request.
- No channel or transmit-power changes without RF evidence and rollback.
- Every requested repair still returns a complete diagnosis and explicitly identifies what additional controller telemetry is required.

## Validation

`python3 -m pytest platform/tests/test_ag32_unifi_network_ops.py -q`

The regression suite verifies that Wi-Fi/UniFi requests never run the generic email/home digest path, detects unavailable APs and 2.4 GHz client pressure, and remains fail-closed for destructive/network-impacting actions.
