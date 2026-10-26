# Flip the Switch: direct build playbook for 3–7 November 2026

**This is a plan, not a deployed Switch workflow.** Operate without relying on DevSwarm/Temporal/Cursor. Prefer local Python, direct Git, local inference and one isolated Switch host. If a plugin/connector cannot perform a step, document the exact limitation instead of manufacturing success.

## Already verified 26 October
- Registration confirmed by official WeMakeDevs email dated 22 October (Ecuador local); keep personal identity details private.
- Base source in Rafa-Innerchispa/innerops-agentic-platform / prep/flip-the-switch-2026 / hackathons/flip-the-switch-2026.
- Standalone portable Git bundle exists from direct local preparation; original base commit 7525b3141aeae86832d065de34a2e93830120762.
- 24 unit tests passed locally. Offline gate PASS (no Switch connection, no production hardware).
- Remote standalone GitHub repository is still NOT verified as created.

## Preparation before event
1. Store the standalone source and portable bundle; create a new private repository manually if the connected GitHub API cannot create it.
2. If publishing: remove any private data and use only competition-safe synthetic fixture, tests and disclosure documents.
3. Choose a Windows laptop with Docker Desktop or an isolated VM; Switch Console supports Windows, Linux and macOS in current official resources. Confirm disk, RAM, Docker health and availability before attempting the setup.
4. Reserve ports away from existing InnerOS services. Do not install on AMD production or expose Home Assistant/UniFi/NVR credentials.
5. Read quickstart https://docs.switchagents.ai/switch-rooms/getting-started and the latest released agent protocol. Resolve any mismatch between promotional-site wording and released docs by testing the pinned version.
6. Draft messages, demo scenario and short video outline. No event-period integration code before official start.

## Official event start — Tuesday 3 Nov at 13:31 Ecuador
1. Pin version, collect version output and actual startup log.
2. Start Switch and the bundled Mattermost chat on an isolated computer; create a human-owned account and team room.
3. Register a dedicated custom triage agent using the officially supported agent protocol. Keep credentials in a local secret manager or environment file NOT tracked by Git.
4. Implement connection/message handling (addressed-only events, scoped actor and room, reconnect, cursor, dedupe). At least one authenticated real message must receive a response in the same Switch room.
5. Integrate only the synthetic event-neutral library, then add a second verifier agent if the single-agent path is stable.
6. Create an approval gate tied to authenticated room actor identity; reject naked chat text, wrong actor, wrong room, expired or replayed approvals.
7. On approved synthetic remediation, verify the expected state using an independently testable readback. Post an evidence digest marked synthetic. On denial, zero changes.

## Safety and verification
- Run existing offline gate after every integration change.
- Build separate E2E tests with room-event fixtures: no approval, rejection, authorized approval, unauthorized actor, duplicate/replay, reconnect, wrong target and readback failure.
- Do not confuse HTTP ACK with successful remediation, or a SHA-256 checksum with a cryptographic signature.
- No real infrastructure commands in this hackathon: customer network/device credentials must never enter the example.

## Final day — Saturday 7 Nov, deadline 13:29 Ecuador
1. Reproduce on a fresh clone and collect complete setup command output.
2. Record a 2–3 minute screen capture that visibly shows a human and agent(s) collaborating inside Switch.
3. Audit source for credentials, personal data, and customer's network details. Make the standalone repo public only after passing the audit.
4. Add README, architecture, license disclosures, new vs pre-existing build log and screenshots.
5. Participant submits the project manually under the verified account. Record the confirmation URL or receipt and only then mark submission done.

No cron/automation is assumed for this work. Opening a new chat after the event start is the trigger for directly implementing and running the Switch integration. 
