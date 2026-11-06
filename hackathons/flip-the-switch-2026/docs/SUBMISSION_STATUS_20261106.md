# Submission readiness — 6 November 2026 (Ecuador)

**Not submitted.** Competition deadline: Saturday 7 Nov 13:29 Ecuador.

## What was built and validated

- Pre-existing synthetic incident engine imported from Oct 26 pre-event baseline.
- Nov 6 Switch custom-agent candidate: WS events, HTTP messages, strict room and sender approval gate, replay/timeout checks, bounded synthetic-only remediation, SHA-256 evidence receipt, cursor/connection ID and durable local outbox.
- Optional local-model reasoning via OpenAI-compatible endpoint; never authoritative for approvals.
- Windows read-only dual-Wi-Fi routing/LAN diagnostic, one-time registration CLI with private credential file, room discovery, doctor, runner, judge video outline.
- Tests verified independently in isolated container, including fake Switch-compatible WebSocket + HTTP test server. That test **is not a live Switch deployment**.

## Remaining requirements before judges can reproduce a valid submission

- [ ] Switch Console installed and running with real Switch API at `/health`.
- [ ] One human account and agent share a real Mattermost/Switch room.
- [ ] Correct agent API key and active WS connection, real addressed message and HTTP response.
- [ ] Identity-bound denial and approval tested in the real room (only synthetic fixture changes).
- [ ] Screenshot and screen recording of the real workflow, not mock footage.
- [ ] Standalone GitHub repo publicly accessible with no credentials/data.
- [ ] Human submitted manually via WeMakeDevs and kept a receipt.

## Honest evidence labels

- `LOCAL TESTED`: packaged code and tests run successfully, including mock WebSocket/HTTP.
- `REAL SWITCH VERIFIED`: **not claimed** until actual server, participant identity and room exchange verified.
- `HARDWARE VERIFIED`: **not claimed**; AMD 1.5 / Intel 1.4 not directly reachable from this isolated container.
- `SUBMISSION SENT`: **not claimed**; registration at Luma / email is not equivalent to a final submission.

Owner can install Switch and connect the local bridge using [Spanish runbook](URGENT_RUNBOOK_20261106_ES.md). A teammate or Antigravity can assist with the read-only Windows checks but must not touch production routing, devices or credentials.