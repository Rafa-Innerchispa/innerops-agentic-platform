# InnerOS Incident Room

**A human-approved, local-first physical-operations workflow for Switch Rooms.**

**Entry:** Flip the Switch Hackathon 2026 · Best Business Workflow · InnerChispa LLC.  
**Submission deadline:** November 7, 2026, 23:59 IST (13:29 Ecuador).  
**Build truth (Nov 6):** Code and offline transport tests have passed, **but a live Switch → Home Assistant round trip and submission have not yet been verified**. They will be marked complete only with real evidence.

## What happens in a live demonstration

A human operator in a real Mattermost room asks `@inneros-incident-triage` to inspect a **real** smart-home light. Switch delivers the message to a purpose-built Python agent through the official agent protocol. The agent reads Home Assistant (HA) directly and posts the state and timestamp back in the same room. Only an exact, short-lived approval from the configured human identity can authorize a write to an expressly allowlisted `light.*` entity. The agent then reads HA again and reports **VERIFIED** or **UNVERIFIED**. A Home Assistant readback is *not* a separate optical sensor or a digital signature.

```mermaid
flowchart TD
  Human[Human operator in Mattermost] --> Switch[Switch Rooms]
  Switch --> Bridge[InnerOS Incident Room custom agent]
  Bridge --> Read[HA live REST state read]
  Read --> Bridge
  Bridge --> Gate{Human approval and allowlist?}
  Gate -->|No| Deny[BLOCKED, no service call]
  Gate -->|Yes| Act[HA turn_on / turn_off, one light]
  Act --> Verify[Fresh HA readback and integrity digest]
  Deny --> Switch
  Verify --> Switch
  Bridge -.-> Optional[Optional read-only InnerOS MCP summary]
```

**Switch is essential:** there is no collaboration or authorization without an addressed, authenticated Switch room event. A standalone test fixture is not claimed as a contest submission. The assistant `switch-buddy-admin` (Codex) is part of Switch setup; the independent Python agent does **not** require Codex, Antigravity or a paid LLM to perform the live HA workflow.

## Verified implementation vs. unfinished steps

| Component | Status |
|---|---|
| Python domain contracts, evidence checks, 78 offline unit tests | Tested locally |
| Agent protocol WebSocket + HTTP, reconnect journal, identity and replay guards | Tested against fake server, *not production Switch* |
| Real HA REST client with entity allowlist and guarded `light.*` writes | Implemented; tests run with fakes |
| Optional InnerOS MCP read-only adapter and voice dictation normalization | Implemented; live endpoint not yet proven |
| Windows Switch Console + Mattermost room | User-installed; room `#inneros-live-operations` observed |
| Reply from custom agent in real room | **Not verified** |
| One real light read, approval, execution and readback in room | **Not verified** |
| Final video and manual WeMakeDevs submission | **Not verified** |

## Fast setup on Windows

From this project directory in PowerShell (with Python installed):

```powershell
.\scripts\preflight_windows.ps1             # read-only: Switch localhost, CLIs
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[switch]"
.\.venv\Scripts\python.exe scripts\submission_preflight.py
```

**Starting point:** [Spanish restart & delivery guide](docs/REENTRADA_Y_ENTREGA_20261106_ES.md). The guide explains (a) `!agents-status` to troubleshoot a silent Codex agent, (b) Gateway API Keys for a custom agent, (c) `register_agent.py`, (d) room/user IDs and (e) HA live readback. For judges: [video storyboard](docs/VIDEO_REAL_CHECKLIST_EN.md).

The Switch API URL must be read from the installed Console. `http://127.0.0.1:8000` is a *documentation example*, not a confirmed address for every Windows installation.

### Register a custom agent once

In Switch Gateway, create a **registration** API key using the actual owner account. Do not save secrets in Git:

```powershell
$env:SWITCH_REGISTRATION_KEY = Read-Host 'Switch registration key'
.\.venv\Scripts\python.exe scripts\register_agent.py --url http://127.0.0.1:8000
Remove-Item Env:\SWITCH_REGISTRATION_KEY
.\.venv\Scripts\python.exe scripts\discover_rooms.py
```

Use the actual server port in `--url`. Invite `inneros-incident-triage` to the existing room via Switch Console. Extract authentic Switch room and user IDs using `discover_rooms.py`, not by guessing the identity from a Mattermost display name.

### Read devices before any mutation

Set these environment variables **only in the operator's private PowerShell session**:

- `HA_URL`: private LAN Home Assistant REST base URL, e.g. `http://192.168.x.y:8123`.
- `HA_TOKEN`: limited-purpose Home Assistant token; never commit or share.
- `HA_ALLOWED_LIGHTS`: exact safe HA entity IDs, e.g. `light.study_lamp` (example, not a real device).
- `SWITCH_ROOM_ID` and `SWITCH_APPROVER_ID`: real IDs from Switch.

Keep `HA_ENABLE_REAL_ACTIONS` **unset** at first. Then run:

```powershell
.\.venv\Scripts\python.exe scripts\discover_ha_lights.py
.\.venv\Scripts\python.exe scripts\run_live_homeassistant.py --doctor
.\.venv\Scripts\python.exe scripts\run_live_homeassistant.py
```

After `@inneros-incident-triage !state light.<exact_id>` succeeds in the real room, a person who controls that single low-risk light may explicitly opt in to live switching by setting `HA_ENABLE_REAL_ACTIONS=YES` and restarting the agent. A proposal needs a separate action-specific `!approve HA-...` from the configured human. `!deny` and wrong/expired/replayed approval never call HA services. No broad `toggle`, router, door, alarm, outlet, camera or security action is supported.

## Reproducible offline tests

```bash
python -m pip install -e .
python -m unittest discover -s tests -q
python scripts/preflight.py
python scripts/submission_preflight.py
```

`submission_preflight.py` has explicit `live_switch_verified=false` / `live_home_assistant_verified=false` flags by design: **local tests cannot stand in for a real room demo**.

## Existing intellectual property and event work

**Pre-existing before Nov 3:** InnerOS/Physical Guardian architecture, domain contracts for synthetic incidents, local inference infrastructure and initial offline tests; see [reuse manifest](docs/REUSE_MANIFEST.md).

**Built during hackathon:** Python agent protocol bridge, credential registration, journaling and replay protections, live Home Assistant light policy/REST client, read-only InnerOS MCP adapter, voice input parser, Windows readiness scripts, source tests and the real workflow integration effort.

Only a restricted, reviewable demonstration adapter is shared. Customer installations, real client networks, credentials and private InnerOS source are **not** included. The owner's final publication and any license grants remain subject to the event's [official rules](https://www.wemakedevs.org/hackathons/switch/rules).

## Links

- [Organizer](https://www.wemakedevs.org/hackathons/switch) · [Rules](https://www.wemakedevs.org/hackathons/switch/rules)
- [Switch agent protocol](https://docs.switchagents.ai/switch-rooms/internals/agent-protocol)
- [Agent connection and liveness](https://docs.switchagents.ai/switch-rooms/internals/agent-connection)
- [When an agent doesn't answer](https://docs.switchagents.ai/switch-rooms/using/agent-not-answering)

**Status honesty:** No claimed live physical demonstration, judge submission or prize until backed by actual recorded evidence.

## Optional local Qwen explanation of real telemetry

If the operator can reach a **locally hosted**, OpenAI-compatible model endpoint (for example via an SSH tunnel to the AMD host), set `LOCAL_MODEL_URL` and the exact `LOCAL_MODEL_NAME` privately. The `!analyze light.ACTUAL_ID` command obtains a fresh, allowlisted Home Assistant state and asks Qwen to explain uncertainty. This read-only model output is never used as approval and cannot call HA actions. Without a model endpoint, the command still returns the verified HA observation with `LOCAL AI NOT CONFIGURED`. Its availability must not be represented as part of the demo unless tested.

Current offline acceptance: **83 local tests** (including five read-only local AI safeguards). These do not certify a live Switch room or physical device.

### Copy-ready hackathon submission

[Submission form answers (English)](docs/FINAL_SUBMISSION_FORM_20261106_EN.md) and [actual video shot list](docs/JUDGES_VIDEO_SCRIPT_EN.md). Both distinguish complete offline code from real Switch/HA E2E evidence.