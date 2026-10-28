---
name: qlink-field
description: "Use this skill for a technician's local, read-only Vantage QLink CLMNES050 serial diagnosis in InnerOS. Never use for automatic firmware/configuration writes."
---

# Field use: Vantage QLink

The user connects an onsite technician laptop via a verified RS-232 cable to an **authorized** Vantage QLink controller. This plugin runs on that laptop, not on the remote AMD/Intel node.

## Before using
- Confirm client/site authorization and that installation is electrically safe.
- Verify the port: the CLMNES050 front DB9 is a diagnostic/programming connector; for third-party continuous control, prefer the documented terminal board **Port A**, wired/verified by a qualified installer. Never infer pinouts.
- Confirm the official QLink programming client has disconnected before attempting another session. Opening a passive serial port can block another client.
- The client fault investigation is recorded privately; a suspect wall keypad stays isolated until an electrician verifies its wiring.
- Do **not** press Reset or change addresses as part of a read-only investigation.

## What is implemented (v0.1.0)
1. `vantage_serial_ports`: inventory of local adapters/COM ports.
2. `vantage_qlink_capabilities`: truthful feature matrix.
3. `vantage_qlink_observe`: passive capture for up to 60 seconds (no serial TX), **only if unsolicited messages are already being emitted**.
4. `vantage_qlink_backup_manifest`: SHA-256 audit of existing local QLink backups from an authorized directory, no parsing or writes.

## What is NOT implemented
- Relay/scene control, VGC/VLC command execution, QLink programming, and Home Assistant/Alexa entity exposure.
- Automatic master discovery through USB without an actual connected adapter.
- Direct remote use from the ChatGPT web MCP server. A scoped authenticated laptop relay is needed.

## Operating rules
- Never claim a keypad/button state is a real Station Bus relay state.
- Never transmit raw commands, flash firmware, reset, or write controller memory through this plugin.
- Do not use a service port or line inside a power cabinet without first verifying pinout and electrical separation.
- Save metadata per tenant/site; do not upload private backup files to public GitHub.
- QLink project extraction requires compatible **official QLink software** and qualified operator supervision. Capture both **Backup Flash** and **System** versions before changes.
- Produce a technical report with source, timestamps, raw and decoded evidence, unknowns, and confidence.
