# Live physical-device demo handoff: 6 November 2026

This is a **status/implementation handoff**, not evidence that live device control or Switch submission has happened.

## Change of product focus

The owner explicitly rejected synthetic devices as the competition demo. The target is **real physical Home Assistant light control** through an authenticated human-agent Switch room.

Primary flow: Switch/Mattermost human -> custom-agent WebSocket/HTTP bridge -> code-level policy gate -> real Home Assistant REST GET/POST for one allowlisted light -> fresh Home Assistant state readback -> evidence receipt in same room.

Optional proof of actual InnerOS connection: `!inneros` invokes **only** registered low-risk read-only `network.communication.coverage.v1` for `home_pcdoctor_lab` through MCP with an owner-authorized credential. The live snapshot from 6 November showed 90 registered devices, but 53 STALE and 37 UNKNOWN reachability statuses. Do NOT call this 90 live devices.

## Direct code delivery produced in local isolated development

- New `src/inneros_incident_room/live_homeassistant.py`: strict `light.*` allowlist, no generic switch/plug/lock/alarm/camera controls, GET current status, human actor+room+exact one-use action approval, TTL, real `light.turn_on/off`, fresh GET readback; no synthetic fallback.
- New `src/inneros_incident_room/inneros_live.py`: optional read-only MCP SDK v2 client, reports only safe aggregate counts.
- New `scripts/discover_ha_lights.py` (read-only listing), `scripts/run_live_homeassistant.py` (real startup).
- Updated Switch transport to allow a separate policy factory and handle blocking device requests off the event loop.
- Added `tests/test_live_homeassistant.py`, and `docs/DEMO_REAL_HOME_ASSISTANT_20261106_ES.md`.
- **72/72 offline tests PASS**, 50 text-file preflight PASS, clean bundle/ZIP built from local Git commit `f89bedbb302a6d437756607b910edc2ee56803f9`.
- The new physical-device files currently exist in the portable ZIP/BUNDLE delivered through ChatGPT, **NOT YET synced into this GitHub branch**. Do not claim they are on GitHub until imported and checked there.

## Validated infrastructure

MCP Small and A2A responsive, AG-60 home site registry read-only retrieved, Intel and AMD servers online. Home Assistant API credentials and the actual Switch Windows room are NOT available to ChatGPT, so no live action was attempted.

## Minimum owner-side steps

1. From Windows with Home Wi-Fi, open actual Home Assistant and generate a dedicated token privately.
2. Extract the new portable ZIP, set `HA_URL` and `HA_TOKEN` *in the process environment*, and run `py scripts/discover_ha_lights.py`.
3. Select exactly one non-critical, currently reachable light in `HA_ALLOWED_LIGHTS`. Keep `HA_ENABLE_REAL_ACTIONS` unset for the read-only doctor phase.
4. Install Switch Console locally, register agent once, and set `SWITCH_ROOM_ID` and `SWITCH_APPROVER_ID` based on real provider event IDs.
5. Run `py scripts/run_live_homeassistant.py --doctor`, then enable `HA_ENABLE_REAL_ACTIONS=YES` only for the deliberate approved one-light test, and run agent.
6. Test `!lights`, `!state light.X`, `!propose light.X on`, `!deny ID`, repeat proposal, and `!approve ID` in a real Switch room.
7. Capture real light and HA state video, verify receipt, publish new repo after scrub and submit personally before Nov 7 13:29 Ecuador.

No router changes and no use of switch Ethernet hardware. Never paste HA/MCP bearer tokens, household IPs, or private device lists into a public competition repository.
