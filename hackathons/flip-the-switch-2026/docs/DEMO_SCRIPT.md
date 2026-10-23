# Planned 2–3 minute judge demonstration

**Not filmed or implemented as of 2026-10-22.** All references to Bellini are scenario inspiration, **not live access**.

00:00–00:20 — Operator introduces the practical problem: a facility camera unavailable, team messages disconnected from AI actions, no closure proof.

00:20–00:45 — In a real Switch-connected Mattermost room, a human sends an incident. RalphiIA participates as a named agent and reads a fictional fixture; show the room member list.

00:45–01:10 — Agent posts a proposed action with target, scope, risk and reason. Another specialist agent optionally checks the diagnosis. The proposed action is `simulate_restart`, never a real reboot.

01:10–01:30 — Human first **denies**. Prove no synthetic state change and an audit event is posted in the room.

01:30–01:55 — Human creates a *new*, correctly correlated approval. Show the bounded action running against the fixture, not infrastructure.

01:55–02:20 — Independent readback verifies the synthetic result. Agent posts evidence receipt and closes the incident in the room. Explain that an ACK alone is not proof.

02:20–02:45 — Show fresh-clone tests, repository and build-log attribution. Point out that Switch is central and local models/InnerOS are reusable, not new event work.

### Screenshots needed during the event

- Switch Console / Mattermost room with human and agent member identities.
- Agent's actual message in Switch room with incident ID.
- First human denial; no state change.
- Second, correctly scoped human approval and operation.
- Independent verification and receipt digest in the room.
- Public repo, CI green, event build log and final 2–3 minute video.

Do not paste a synthetic JSON printout and describe it as evidence of an actual Switch integration.
