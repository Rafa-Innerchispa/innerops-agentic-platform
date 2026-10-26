# Submission copy draft — NOT submitted (26 Oct 2026)

## Project title
InnerOS Incident Room: Human-approved AI incident response in Switch

## Category
Best Business Workflow

## Short description
When a camera goes offline, operators need more than another alert. InnerOS Incident Room is a collaborative incident-response workflow where a human operator and specialized AI agents work together inside a Switch room. A triage agent investigates the report, a verifier challenges the proposed remedy, and a human explicitly approves or rejects a bounded response. The synthetic scenario ends with independent simulated readback and a traceable evidence receipt in the same room. Local-first inference and separation from production devices keep the example reproducible and safe.

## The problem
In many small technical teams, incident evidence lives in monitoring dashboards, approval decisions live in chat, and fixes happen in an operator's head. That fragmentation produces delays, unclear ownership and unverifiable outcomes.

## Why Switch is essential
Switch must be the actual shared room/event transport and identity source, connecting a real human participant with agent teammates in Mattermost. If Switch is removed, the collaborative approval and evidence loop must stop. This is NOT yet implemented as of 26 October.

## Existing versus new
Pre-existing and honestly attributed: InnerOS/ARIA, RalphiIA, FieldOps design, local inference infrastructure, generic synthetic incident contracts, checksums and offline tests.
To build exclusively DURING Nov 3–7 Ecuador event window: Switch setup, real room and agent registration, custom agent protocol adapter, synchronized human decision, agent collaboration, room evidence delivery and recording.

## Demo plan (2 min 40 sec, record only after real integration works)
- 00:00–00:20: Introduce the problem and show the real Switch-connected Mattermost room.
- 00:20–00:45: Human posts a synthetic camera failure; addressed RalphiIA reads it in the same room.
- 00:45–01:10: First agent diagnoses; second agent checks source and remediation scope.
- 01:10–01:40: Human rejects proposed action; show that no synthetic state changes.
- 01:40–02:05: Human explicitly approves a new bounded request; fixture-only action runs.
- 02:05–02:25: Independent synthetic readback and verifiable digest receipt appear in room.
- 02:25–02:40: Show project README, tests and disclosure of pre-existing code.

## Evidence required before shipping
- Confirm official registration (email received 22 Oct Ecuador; do not publish private email or participant legal name).
- Actual Switch version, screenshot and addressed-room message log.
- Authenticated human identity, denial and approved run traces.
- Retry/reconnect and duplicate event test output.
- Clean clone/setup/test proof, green Actions on standalone repository.
- Public repository audited for secrets and customer details.
- Real screen recording and human-initiated official submission receipt.

## Honest status
On 26 October the synthetic generic library is complete for preparation and passed 24 local tests. The Switch event integration, human-agent room, public standalone GitHub repo and final submission are NOT yet complete. Do not paste this draft into the submission form as a claim of finished capabilities.
