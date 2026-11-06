# Judge demo narrative — 2:35 (record after real Switch works)

> No prerecorded mock footage should be presented as a live Switch integration. All camera and network data are intentionally synthetic. Replace `[SCREEN]` with genuine recordings.

**00:00–00:20 / Open real Switch room**

"Hi, I'm Rafael from InnerChispa. Our IT operators face a common problem: an alert can be easy to raise but hard to investigate, authorize, and close with evidence. InnerOS Incident Room uses Switch to bring an operator and an agent into one shared incident room."

**00:20–00:55 / Human requests incident investigation**

[SCREEN: A human types `@inneros-incident-triage !incident` in the REAL Mattermost room; the agent replies.]

"The camera is offline. A separate synthetic network source says the link is up. Our local-first triage tells us what is known and what we still cannot prove. Switch delivers the human's request to the agent and returns its analysis to the same room."

**00:55–01:20 / Denial and fail-closed policy**

[SCREEN: The operator sends a denial for the proposed action; the state remains degraded.]

"The model cannot take a corrective action just because a prompt suggests it. The approval guard is enforced in code. Here, the authorized operator denies the request, and nothing changes."

**01:20–01:55 / New request + human-approved synthetic response**

[SCREEN: New incident, human approves exact action ID, visible agent reply.]

"This time the operator approves a bounded response. The demo executor changes a synthetic camera state only, then performs a simulated readback. We do not connect to or control production cameras."

**01:55–02:20 / Audit and failure modes**

[SCREEN: Evidence receipt in same room and a terminal showing the tested replay/identity safeguards.]

"The result includes a correlation ID, policy decision, final state and a SHA-256 integrity digest. It blocks wrong identities, wrong rooms, replayed messages and expired approvals. A hash is an integrity check, not a cryptographic signature."

**02:20–02:35 / Technical proof**

[SCREEN: Actual repository and successful tests, with PRE-EXISTING versus HACKATHON-BUILT disclosure.]

"Our agent works through Switch's WebSocket and HTTP protocol, while optional inference runs locally on our AMD server. The repository includes reproducible tests and documents what we reused and what we built during the competition."

## Claims checklist before final video

- [ ] REAL Switch room footage (not test double)
- [ ] Human operator typed into Mattermost
- [ ] Agent returned a response through Switch
- [ ] REJECT and APPROVE tested using actual Switch participants
- [ ] All synthetic labels visible
- [ ] No private IPs, credentials, customer information or raw logs
- [ ] Final repo public and accessible to judges