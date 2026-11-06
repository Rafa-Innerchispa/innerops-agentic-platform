# InnerOS Incident Room

**Human + AI agent incident response for real-world infrastructure, with safe local-first execution and auditable evidence.**

> **Status (2026-11-06): Event-period candidate Switch client implemented and locally tested against a fake Switch-compatible server. REAL Switch/Mattermost connectivity and hackathon submission remain unverified.**
> Pre-existing generic synthetic incident primitives are attributed separately. The event-period WebSocket/HTTP client and workflow were developed on November 6; no claim of live Switch connection or actual submission until evidenced.

## Competition

- **Event:** [Flip the Switch Hackathon](https://www.wemakedevs.org/hackathons/switch)
- **Track:** Best Business Workflow
- **Organizer:** WeMakeDevs, DevTools Academy and Switch
- **Hacking window in Guayaquil (UTC-5):** **November 3, 2026, 13:31** through **November 7, 2026, 13:29** (official schedule uses IST).
- **Deliverables:** public repo, reproducible setup and demo video, subject to organizer rules.
- **Entry:** A human entrant must register/submit personally, not via automated bots.

## Core idea

An operator and at least one AI agent work in the **same Switch-connected team-chat room** to triage, investigate and safely close an infrastructure incident. A second agent may collaborate. The room is the shared record of requests, evidence, decisions, approvals and closure.

**Planned example:** a *Bellini-inspired, wholly synthetic* camera connectivity incident. No real customer network information, passwords, IP ranges, device IDs or identifiable CCTV footage will be published. Production customer integrations are out of scope for the competition demo unless separately authorized, sanitized and independently verified.

### Intended real Switch workflow (client implemented; server-side E2E NOT verified)

```text
Human posts synthetic alert in team chat
  -> Switch routes to RalphiIA bridge
  -> InnerOS/FieldOps reads synthetic fixture
  -> Agent analyzes and proposes bounded action
  -> Human approves or denies in the shared room
  -> Local synthetic executor performs only approved simulated action
  -> Independent verifier checks fixture result
  -> Evidence receipt and closure posted in room
```

Switch must be central and **a human must demonstrably collaborate with an agent**. A standalone local simulation is useful preparation, but cannot substitute for the Switch event-period workflow.

## Pre-existing reusable synthetic primitives

- Portable, offline Python domain contracts for synthetic incidents and action proposals.
- Fail-closed approval and scope guard for a synthetic `simulate_restart` operation.
- Read-only simulated observation and independent readback of in-memory state.
- Canonical JSON SHA-256 receipt digest with a separately testable integrity checker, **not a digital signature or tamper-proof audit log**.
- Injectable synthetic readback to test failed verification without calling real devices.
- Strict, checksum-verified standalone export, offline gate and 24 passing automated unit tests.
- Automated unit tests and GitHub Actions CI definition.
- All demo data is deliberately synthetic; no network or external model is used.

## Offline run (no Switch, no Docker, no credentials, no external API)

From the project root:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m inneros_incident_room.cli --decision deny
python -m inneros_incident_room.cli --decision approve
python scripts/offline_gate.py
python scripts/bootstrap_standalone.py --destination /tmp/incident-room-clean
```

Alternatively, run without installing (Linux/macOS):

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m inneros_incident_room.cli --decision approve
```

Every output explicitly includes `fixture_only: true`, `switch_connected: false`. These are honest labels, not event evidence.

## Repo map

- `src/inneros_incident_room/`: generic, offline-safe incident primitives (PRE-EVENT reusable components)
- `fixtures/`: fabricated demonstration data; no actual customer topology
- `tests/`: policy, denial, approval, scope, evidence integrity and offline export tests
- `scripts/offline_gate.py`: one-command offline-only reproducibility report
- `scripts/bootstrap_standalone.py`: checksummed local export for a new Git repository
- `docs/LOCAL_DIRECT_EXECUTION_20261026.md`: self-contained local recovery and instructions
- `docs/ARCHITECTURE.md`: architecture and planned Switch boundary
- `docs/SWITCH_INTEGRATION_PLAN.md`: official custom-agent protocol and event-period implementation plan
- `docs/REUSE_MANIFEST.md`: pre-existing InnerOS lineage and reuse boundaries
- `docs/HACKATHON_BUILD_LOG.md`: timestamped work ledger; append genuine event work here
- `docs/SUBMISSION_CHECKLIST.md`: reproducibility, demo, rules, presentation and manual submission
- `docs/PROJECT_BRIEF_ES.md`: overview in Spanish
- `AGENTS.md`: bounded coding-agent instructions


## 6 Nov 2026: hackathon-period adapter (candidate)

A Switch WebSocket + HTTP single-agent integration candidate is now implemented
in `src/inneros_incident_room/switch_event.py`, with 17 new offline tests.
The combined suite passes **41/41 local tests**. It has NOT been connected to a
real Switch/Mattermost instance, so the contest workflow and submission remain
**unverified and incomplete**. See `docs/EVENT_IMPLEMENTATION_20261106.md`.

```bash
python -m pip install -e ".[switch]"
python -m unittest discover -s tests -v
python -m inneros_incident_room.switch_event  # requires private env vars
```

## Safety and limits

- **No live device mutations** from this repository.
- **No real API keys**, credentials, NVR configurations, internal IP addresses or confidential records committed.
- Local models preferred, but none are required for the offline prep library.
- Any future live execution is separate, explicitly authorized, scoped, verified and auditable.
- No claims of working Switch, Slack, Mattermost or real devices until verified end-to-end.

## Pre-existing technology and attribution

InnerOS/ARIA, RalphiIA, MCP, DevSwarm, FieldOps, model routing, physical-infrastructure integrations, human approval and evidence contracts exist independently of this competition. Sources linked in [reuse manifest](docs/REUSE_MANIFEST.md). Preparatory work here does not claim those components were built during the event. New event work starts inside the official hacking period, tracked in the build log.

## Useful links

- [Official event](https://www.wemakedevs.org/hackathons/switch)
- [Official rules](https://www.wemakedevs.org/hackathons/switch/rules)
- [Official schedule](https://www.wemakedevs.org/hackathons/switch/schedule)
- [Switch quickstart](https://docs.switchagents.ai/switch-rooms/getting-started)
- [Custom agent protocol](https://docs.switchagents.ai/switch-rooms/internals/agent-protocol)
- [Switch source](https://github.com/sandbox-quantum/switch)

Prepared by InnerChispa LLC. See `docs/SUBMISSION_CHECKLIST.md` for remaining work and explicit TODOs.


## Updated 6 Nov 2026: runnable Switch client, still requiring real server proof

The event-period implementation now includes a WebSocket/HTTP Switch client,
fail-closed identity checks, persistent synthetic approval/reply state, an
optional OpenAI-compatible **local** model reasoner, one-time private-file
agent registration, a read-only Switch API doctor, and room discovery.
All tests that use a Switch transport run against an **explicit fake server**;
this is not evidence that Switch was deployed or used for the competition.

**Start here:** [Urgent Spanish runbook](docs/URGENT_RUNBOOK_20261106_ES.md).
The exact command sequence for Windows and dual Wi-Fi access is in that guide.

- `scripts/register_agent.py`: creates a Switch agent once; saves its API key
  outside Git in the current user's home directory (no stdout secret).
- `scripts/discover_rooms.py`: lists registered agent's rooms/participants.
- `scripts/run_agent.py --doctor`: checks API health + agent API-key access,
  without changing settings or publishing room messages.
- `scripts/run_agent.py`: runs the actual Switch WS/HTTP agent after configured.
- `scripts/diagnostico_lan.ps1`: Windows LAN connectivity/routing diagnostics;
  **read-only**, no automatic routing modifications.
- `src/inneros_incident_room/local_reasoner.py`: sends ONLY synthetic facts to
  a local vLLM/Ollama OpenAI-compatible endpoint. If inaccessible, deterministic
  triage continues; the model cannot approve or change any action.
- `tests/test_switch_transport_integration.py`: real socket and HTTP test against
  an explicitly fake Switch-compatible server.

**Actual contest submission:** only after real Switch/Mattermost messages,
README validation, video and a standalone public repository. The participant
must personally submit via WeMakeDevs.