# Judge video script: real physical evidence, under 3 minutes

**Record only the actual working flow** on Switch Console / Mattermost, Home Assistant and, where possible, a visible physical lamp. This is a proposed script, not a claim that the run is already complete. No synthesized screenshots, fake Switch server or fake HA endpoint may be represented as real. Avoid personal account details, local IPs, tokens and authorization headers.

## 00:00–00:22 — Hook, show physical lamp and active room

> "Most AI agents can tell you to turn a device on. Our question is harder: who authorized the change, and did the real device actually respond? I'm Rafael from InnerChispa, and this is InnerOS LiveOps, built on Switch."

[Show a real lamp and a running Switch Mattermost room named `#inneros-live-operations`.]

## 00:22–00:58 — One real observation, not a simulated alert

> "The operator asks the agent for a live reading. Switch delivers the request and brings the result into our shared room. This state comes from Home Assistant on our own network, not from a fabricated fixture."

[Show a HUMAN posting `@inneros-incident-triage !state light.ACTUAL_ID` and the agent replying with current on/off and fetch timestamp. Make sure this actually works before narrating it.]

## 00:58–01:22 — Optional local AI explains uncertainty

> "Local Qwen can interpret what the data means and, just as importantly, what it cannot prove. The model can explain; it cannot act on a device."

[Show `!analyze light.ACTUAL_ID` only if a real local model replied. Otherwise omit this section and spend 24 seconds on architecture with true status flags.]

## 01:22–02:12 — Deny, approve, independent service readback

> "Actions are governed by code, not promises in a prompt. A human proposes one operation for one allowed light, sees a time-limited approval ID, and explicitly decides. A denied action does nothing. An approved action uses Home Assistant and then checks the state again. An unavailable device is reported as unverified, not fixed."

[First show a denied proposal. Then propose again and approve only if operator allows a change to an agreed low-risk light. Camera pointed at the lamp should capture the physical response while the HA readback appears on screen. If actuation remains unavailable, DO NOT pretend it happened: show only legitimate read-only collaboration.]

## 02:12–02:43 — Technical validation and business relevance

> "Our Python agent joins through Switch's official WebSocket and HTTP protocol. The code verifies the sender, the room, the exact action and the expiry. It includes 83 local tests and an explicit list of what is and is not proven. The same approach can help a support team manage real facilities without handing unrestricted device controls to an AI model."

[Show the actual GitHub project directory/README, running test command and results, and the live room again.]

## 02:43–02:55 — Close

> "Switch makes the human and the agent teammates. InnerOS makes the device operation local, controlled and verifiable. That's InnerOS LiveOps."

## Prohibited exaggerations

- A Home Assistant readback is not an independent optical/physical sensor; the physical lamp footage adds separate human-visible evidence.
- SHA-256 checksum is not a digital signature or immutable ledger.
- The offline synthetic tests are not proof of a genuine Switch round trip.
- No live room response, no completed integration claim.
- Optional Qwen reasoning must be shown on a genuine endpoint to be described as active.

Deadline: Saturday Nov 7, 2026, 13:29 Ecuador (23:59 IST).