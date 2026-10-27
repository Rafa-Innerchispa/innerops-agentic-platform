# InnerOS Field Plugin — Vantage QLink / Ashley Ruiz (Puerto Azul)

**Status: prototype read-only (2026-10-27). NOT deployed, NOT tested on customer equipment.**
**Client/site:** Ashley Ruiz · Puerto Azul. The service on 2026-10-27 was recovered; the suspect wall station remains isolated pending an electrician's inspection. The upgrade is a **separate phase 2**.

Notion source of truth:
- Diagnosis/closed original visit: https://app.notion.com/p/406cb2deeb0f8132a429dd7ab12124bd
- Phase 2: https://app.notion.com/p/406cb2deeb0f81499312feac253de5c7

## Objective (do not create a parallel home automation stack)

Allow an authorized PC Doctor technician to plug a USB-to-RS232 cable from a **field laptop** into a legacy QLink controller and ask the **local InnerOS AI** to identify devices, inspect a safe serial session, recover a *previously made* QLink backup manifest and plan scenes. Eventually expose **verified** lights and scenes through the **existing InnerOS Home Assistant + AG-60 Device Fabric + Capability Gateway**.

This is not a promise of autonomous programming or Alexa support in v0.1.0. In particular, **Station Bus relay loads are NOT implemented in the community QLink bridge** and must not be misidentified using keypad state.

## Verified existing platform

- Canonical repo: `Rafa-Innerchispa/innerops-agentic-platform`.
- InnerOS `device_fabric.py` already provides AG-60 and has a `home_assistant` provider, REST/WebSocket client in `homeassistant_client.py`.
- **New `vantage_qlink` provider** is intentionally registered `not_validated`: not "ready" until end-to-end hardware validation and approved production deployment.
- Supports real local ports only. Remote MCP on AMD/Intel **cannot access** USB plugged into a different machine unless an authenticated site-scoped relay is implemented and activated.

## Observed devices and electrical context

- Vantage QLink Master `CLMNES050`, suspected displayed firmware `7.88B` (confirm).
- Two STR8RW201/RS8-DIN stations, eight relay channels each; actual station IDs/loads must be inventoried from QLink project before asserting mapping.
- Multiple Station Bus wall keypads; one was associated with a 2 V bus collapse / `Station Bus Short` after lightning and was isolated to recover service.
- 22 V measured at 24 VDC input; ~2 V when shorted; ~22 V on unloaded Station Bus. Do not assume 22 V is within guaranteed tolerance until checking power supply specifications.

## Architecture: portable field bridge, not another controller

```text
Technician laptop at Ashley (authorized on-site)
  -> USB-RS232 adapter + verified wiring/pinout + one exclusive serial session
  -> local InnerOS Vantage MCP field plugin (STDIO, read-only)
  -> **future** authenticated outgoing site relay (mTLS/token + site scoped)
  -> existing InnerOS AMD / Intel agents, Device Fabric AG-60
  -> existing Home Assistant instance (ONLY verified lights/scenes)
  -> optional voice integration/Alexa after end-to-end test
```

A permanent installation needs a small **onsite serial/IP gateway** or tiny Pi/mini-PC to keep RS232 connected 24/7, and a secure connection to central InnerOS. The laptop is for installation/maintenance, not a permanent controller. Native QLink and wall keypads must remain usable when the remote AI, internet or Alexa is offline.

## What is implemented in this branch

- `platform/inneros_core_runtime/vantage_qlink_field.py`: CLI for `--list-ports`, passive capture `--observe PORT`, and SHA-256 manifest for approved existing `.qlk/.bak/.bin` files. No serial writes or QLink project modification.
- `platform/inneros_core_runtime/vantage_qlink_mcp.py`: STDIO FastMCP server for the **onsite laptop**.
- `platform/plugins/inneros-vantage-qlink/`: local plugin package referencing the canonical checkout, with `plugin.json`, `mcp.json`, and field skill. **Not standalone**: requires full InnerOS platform checkout and its Python dependencies.
- AG-60 declares `vantage_qlink` as a not-yet-validated provider. Do not modify the 8001 Small tool list to force additional tools into every session.
- `platform/tests/test_vantage_qlink_field.py`: unit tests that serial observation never writes and that no button event is presented as actual relay state.

### Developer / field use (READ ONLY)

On the laptop with the **full InnerOS repo checkout**, using the virtual environment used for the platform:

```bash
python -m pip install pyserial fastmcp
cd platform
python -m inneros_core_runtime.vantage_qlink_field --list-ports
python -m inneros_core_runtime.vantage_qlink_field --observe COM5 --site puerto_azul_ashley --seconds 10
# Linux typically uses /dev/ttyUSB0 instead of COM5.
```

For existing QLink backups only, run from an approved per-client folder:
```bash
export VANTAGE_QLINK_BACKUP_ROOT="/path/to/private/ashley/qlink"
python -m inneros_core_runtime.vantage_qlink_field --manifest "/path/to/private/ashley/qlink/ASHLEY_FLASH.qlk" --site puerto_azul_ashley
```

For a local AI client supporting stdio MCP, install the **local** `platform/plugins/inneros-vantage-qlink/mcp.json` while running the full InnerOS checkout. Launches `server.py` via the platform's `fastmcp`. The process accesses physical ports **only on that laptop**. Serial device permissions and site authorization still apply.

**Caution:** the RS232 serial port may produce NO passive frames if QLink is not configured to output `VOS`/telemetry. An empty capture is **not evidence of device absence or a failed Master**. No "auto scan" is implemented. The master has a front diagnostic port, but integrator references recommend terminal-board **Port A** for persistent external control. Do not guess DB9 pinout, swap power wires or connect to the 2-wire Station Bus with a serial adapter. Keep mains, relay terminals and RS232 wiring electrically separated.

## Acceptance milestones

| Gate | Evidence required | Status |
| --- | --- | --- |
| G0: restore lighting service | QLink bus short disappears with faulty wall station isolated | Done, 2026-10-27 |
| G1: test local plugin in CI | Unit test pass, tool listing and no TX | Source committed; pending CI |
| G2: onsite read session | Verified COM/port, UART settings, observed response or passively captured frames, no resets | Not tested |
| G3: QLink project backup | Official QLink version matched to firmware; **Backup Flash and System separately extracted by official software**; hashes and secure tenant storage | Not tested |
| G4: command protocol proof | Approved harmless load query plus vetted response; station load `VGC/VLC` protocol validated and true load mapping known | Not tested |
| G5: Home Assistant | Correct state for 16 stations' actual relay loads (where applicable), manual keypad and remote control consistency, offline behavior proven | Not tested |
| G6: optional Alexa | Local/remote control, language/region and privacy confirmed with user account | Not tested |
| G7: supervised QLink programming | Version-matched official QLink project, plan/diff, approval, backup, rollback and post-write commissioning | Not implemented |

### Why relay states are not inferred from button telemetry

- `SW m s b v` reports a keypad/switch event.
- `RGS# m s b v` is a button state.
- `LO m e module load level` relates to an *enclosure* load, **not a Station Bus STR8RW201 load**.
- Station Bus stations require distinct V-commands (reported as `LS` lines, `VGC/VLC` grammar). The linked community bridge does not implement them.
- Only a validated controller response + on-site observation may be exposed as real `light.*` entity state.

## Native programming vs third-party control

- **QLink 4.x** is the legacy project editor; **Design Center** is the InFusion tool and conversion is not lossless. Upgrading may require **reprogramming scenes**, even if DIN stations are compatible.
- Official Vantage guide details extracting **Backup Flash** and **System** using QLink `File > Connect Setup > Local` and reading separately; find matched firmware before connecting.
- AI may suggest changes based on the project, generate an implementation plan, and operate a verified supervised workflow. The current plugin CANNOT write the QLink program or switch relays.
- Never upload a customer's `.qlk` backup, logs or personally identifying data to a public GitHub repository.

## Reference sources
- Vantage Master controller: https://oderlv.com/pdf/Vantage_Master_Controller.pdf
- Legrand QLink-to-InFusion upgrade installation (IS-0575): https://www.legrand.us/p/view-asset?downloadUrl=https%3A%2F%2Flegrand.webdamdb.com%2Fdirectdownload.php%3Fti%3D348557314%26tok%3DvojAad7jMkIxF7MsVhhNKwRR%26token%3D%242y%2410%24doJq8joEItb%2FbzU%2FWCVUQufm9cxQDwH7kkovcghpJufkcZsOAR5a2
- Community bridge and **station load limitation**: https://github.com/imfinlay/vantage-qlink-api
- Control4 QLink integration notes (station loads and RS232): https://drivercentral.io/images/CinSiteIcons/Vantage%20Qlink/Vantage%20QLink%20Light%20Driver_documentation.pdf?1595631264807=
- Crestron RS232 port notes: https://applicationmarket.crestron.com/content/Help/Vantage/q_series_lighting_systems_10_buttons.pdf
