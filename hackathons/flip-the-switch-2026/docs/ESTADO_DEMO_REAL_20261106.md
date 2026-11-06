# Real-device readiness, 6 November 2026

## Verified from InnerOS, before any device commands

- Read-only MCP Small bridge is accessible and A2A reports healthy.
- AG-60 communication coverage successfully read the canonical `home_pcdoctor_lab` site.
- Registry count: 90 devices, but **none of its reachability observations were verified fresh**: 53 STALE and 37 UNKNOWN. Do not claim 90 live or online devices.
- Relevant categories exist in the registry: smart lights, Broadlink remotes and HA-connected devices. No entity ID or live light state was established through the current AG-60 capability. The real HA REST adapter fetches exact states directly at demonstration time.

## What was actually built in the competition period

- A dedicated `live_homeassistant.py` runtime that cannot use synthetic fixtures, only allowlisted `light.*` devices in an owner-controlled Home Assistant installation.
- A new live Switch agent launcher (`scripts/run_live_homeassistant.py`) with mandatory HA connectivity check.
- A read-only inventory tool (`scripts/discover_ha_lights.py`) to select a verified light entity.
- An optional `!inneros` MCP SDK v2 command that calls only the low-risk `network.communication.coverage.v1` capability and explicitly reports stale/unknown data.
- Explicit approve/deny policy bound to real Switch participant and room identifiers; immutable action identifiers, expiration, and one-time execution intent. Actual action uses one HA service call, with GET readback afterward.
- Unit tests and a local fake HA REST contract test, which test the code but do NOT count as evidence of a physical-world operation.

## What is NOT verified

- No physical light change or live Home Assistant REST access from the owner's Windows machine is proven yet.
- Switch Console installation and its human-agent room session were not accessible from this chat; no authentic Switch room message or screenshot has been received.
- The new optional MCP SDK client has not been independently connected to the owner's live gateway from Windows.
- No official hackathon submission receipt or real demo video is available.

## Practical minimum

One live light turning on with an authorized human message in Switch, independently queried via Home Assistant, with the operator visibly showing the physical lamp, is a compelling and honest physical-world use case. Add the `!inneros` MCP inventory read only if a dedicated authorized token is already available; do not delay the verified HA flow by building new auth infrastructure.

No appliance controllers, alarms, locks, routers or customer networks are modified by this demo runtime.