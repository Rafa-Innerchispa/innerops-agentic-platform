# InnerOS Incident Room

**Human + AI agent incident response for real-world infrastructure, with safe local-first execution and auditable evidence.**

> **Status (2026-10-22): Preparation only. Not a functioning Switch integration or a hackathon submission.**
> This folder contains reusable, synthetic incident-domain primitives and event planning documents created **before** the competition build window. The Switch connector, human-agent collaborative room, and actual event workflow **must be implemented and verified during the event**, and are NOT present here yet.

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

### Proposed event-period sequence (NOT yet implemented)

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

## What works today (pre-existing reusable local preparation)

- Portable, offline Python domain contracts for synthetic incidents and action proposals.
- Fail-closed approval and scope guard for a synthetic `simulate_restart` operation.
- Read-only simulated observation and independent readback of in-memory state.
- Canonical JSON SHA-256 receipt digest for change detection, **not a digital signature or tamper-proof audit log**.
- Automated unit tests and GitHub Actions CI definition.
- All demo data is deliberately synthetic; no network or external model is used.

## Offline run (no Switch, no Docker, no credentials, no external API)

From the project root:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m inneros_incident_room.cli --decision deny
python -m inneros_incident_room.cli --decision approve
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
- `tests/`: policy, denial, approval, scope and evidence tests
- `docs/ARCHITECTURE.md`: architecture and planned Switch boundary
- `docs/SWITCH_INTEGRATION_PLAN.md`: official custom-agent protocol and event-period implementation plan
- `docs/REUSE_MANIFEST.md`: pre-existing InnerOS lineage and reuse boundaries
- `docs/HACKATHON_BUILD_LOG.md`: timestamped work ledger; append genuine event work here
- `docs/SUBMISSION_CHECKLIST.md`: reproducibility, demo, rules, presentation and manual submission
- `docs/PROJECT_BRIEF_ES.md`: overview in Spanish
- `AGENTS.md`: bounded coding-agent instructions

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
