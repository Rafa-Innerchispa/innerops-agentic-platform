# Flip the Switch — submission fields ready to paste

**Owner:** InnerChispa LLC. **Entry:** InnerOS LiveOps.
**Deadline:** 7 November 2026, 23:59 IST = 7 November 2026, 13:29 America/Guayaquil.
**IMPORTANT:** The strong 'How we used Switch' text below is **only valid after** a genuine custom-agent reply and real HA readback are observed inside the room. Do not claim these have happened until the operator verifies them. Do not fabricate a video URL. The organizers require a real recording of Switch in team chat.

## Part 1: Project details

### Project title
InnerOS LiveOps: AI Agents Meet the Physical World

### Tracks to select
- Best Business Workflow
- Best Personal or Creative Workflow (the genuine home-device use case also qualifies)

Do not select Best Core Contribution without an assigned, genuine Switch-core PR.
Code with Wispr requires **actual Wispr Flow usage during development** and its Insights > Your usage > Share card. No synthetic card.

### Project description (safe draft, does not claim a finished physical run)
Technicians managing homes and small facilities lose time switching between monitoring dashboards, message threads, and isolated AI agents. The most dangerous part is not detecting a problem but knowing who approved a response and whether the device actually changed state. InnerOS LiveOps brings those decisions into a shared Switch Room, with a self-hosted Mattermost channel and a purpose-built Python agent. The agent is designed to query actual Home Assistant light entities, report fresh observations, optionally explain uncertainty using locally hosted Qwen inference, and propose a narrowly scoped response. A deterministic policy layer, not the language model, checks the authorized Switch sender, exact room, allowlisted light, expiring approval ID, and replay protection. An approved action may change one real light; the agent then queries Home Assistant again and reports VERIFIED or UNVERIFIED with timestamps and an integrity digest. The same pattern applies to small-facility support teams and private home labs. Switch supplies the shared communication and human approval context, while InnerOS supplies local-first device operations. The repo includes 83 offline automated tests and documents which components existed before the hackathon.

### GitHub repository
https://github.com/Rafa-Innerchispa/innerops-agentic-platform/tree/hackathon/flip-the-switch-20261106/hackathons/flip-the-switch-2026

This is an existing public repository's hackathon directory on a dedicated branch, NOT a separate GitHub repository. It has a setup README. A separate repo would be ideal but is not required if the form accepts this URL and reviewers can open the directory. GitHub's default branch contains a different project, so paste the branch/directory link **exactly**.

### Demo video
**REQUIRED — NOT AVAILABLE UNTIL REAL FOOTAGE IS CAPTURED.** Upload a genuine under-three-minute video to YouTube (Unlisted) or Loom and paste that video's actual URL. Do not submit a fabricated URL or screenshots of test doubles as a live Switch integration.

### Live demo / deployment
Leave blank. Switch is self-hosted on the participant's local Windows machine; do not publish Home Assistant or a home IP to the Internet just to create a live URL.

## Part 2: Track details

- Pull requests: leave blank. No verified assigned core PR.
- Blog post: optional. Publish a truthful build article only if time remains after the live demo and video. Link the published URL, not a draft.
- Wispr usage card: upload real app-generated card only if Wispr Flow was actually used to build the project. Otherwise leave blank.
- #HowISwitch post: optional public social post with real facts and a real URL.

## Part 3: How you used Switch

### What to paste ONLY AFTER E2E VERIFICATION
We used Switch Console on Windows with its self-hosted Mattermost bridge and the real channel #inneros-live-operations. A custom Python agent, inneros-incident-triage, joined through Switch's registration API and WebSocket/HTTP agent protocol. The human operator used the Mattermost room to request live Home Assistant state; the agent returned the measured state and timestamp in the same conversation. For a low-risk allowlisted light, a deterministic code-level gate checked the authenticated Switch sender and room, requested an exact expiring approval, and rejected unapproved or replayed requests. After explicit authorization, the agent sent a narrow Home Assistant service call and posted a fresh state readback, marking it VERIFIED or UNVERIFIED. Local Qwen reasoning can add a read-only explanation, but it cannot approve or actuate devices. Switch is essential because it provides the shared room, authenticated participant context, and human decision flow. We did not require Slack, Discord, Telegram, or cloud inference services for the local Mattermost workflow.

**Important substitutions:** If no local Qwen runtime actually answered during the demo, change “Local Qwen reasoning can add a read-only explanation” to “An optional read-only Qwen adapter is included but was not used in the recorded run.” If no physical action was approved/performed, delete the sentence about service calls and present only live readback, not a physical actuation result.

### Honest fallback if E2E cannot be made to work
We installed Switch Console 0.40.1 on Windows, linked its bundled Mattermost instance, and created #inneros-live-operations with a Codex-backed administrative agent. Codex appeared installed and signed in, but its response in the room could not be verified. In parallel we developed a custom Python client for Switch's documented WebSocket/HTTP agent protocol and a guarded Home Assistant bridge. The code passed 83 local tests, including transport against a fake server and an HA mock, but we were unable to verify an authentic Switch-to-Home-Assistant round trip. We are documenting this limitation rather than claiming a physical demo we did not run.

### What did you like about Switch, and what would you improve?
The strongest features are the self-hostable design, bundled Mattermost, shared room context, and open agent protocol. They make it practical to reuse private/local agents instead of rebuilding them for every chat platform. We also like that real participant identities are available to build accountable approval workflows, rather than relying on a name typed in a prompt. Our main friction was operational visibility on Windows Console 0.40.1: Codex was shown as Installed and Signed in, and the agent appeared available, but a room mention did not produce a reply. During room creation, a localhost timeout appeared even though Mattermost eventually created the channel. We would improve end-to-end status reporting from messaging bridge to agent controller, including visible connection state, logs for undelivered mentions, actionable Windows diagnostics, and a first-class short-lived human approval object with replay-safe evidence receipts. These are suggestions based on our setup experience, not proof of a particular upstream bug.

## Final proof checklist — do not call the submission complete before these
- [ ] Actual message to custom agent in `#inneros-live-operations` and real agent reply in the same room
- [ ] Authentic current Home Assistant entity state and its timestamp returned by the agent
- [ ] Optional controlled physical light action approved by authenticated user, actual state re-read, video visibly shows lamp
- [ ] Optional live Qwen read-only analysis **if available**, never makes an authorization decision
- [ ] No credential, device IP, address, customer information or token in screenshots or screen recording
- [ ] Public GitHub URL works in a logged-out/incognito browser
- [ ] 2–3-minute genuine video uploaded to a public/unlisted video URL
- [ ] Human owner submits in WeMakeDevs and saves the receipt before 13:29 Ecuador