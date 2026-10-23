# Switch adapter: event-period work, not implemented yet

**Important:** The official documentation states that current custom agents receive room events over **WebSocket**, not SSE, and use **HTTP** operations for actions. SSE is an older, deprecated path. See https://docs.switchagents.ai/switch-rooms/internals/agent-protocol.

## Correct wire-level plan

1. Select the appropriate local Switch server and chat bridge (Mattermost is included with self-hosted setup); use official releases when testing is authorized.
2. Create a human-owned registration token via Switch Gateway (never commit it).
3. `POST /agents` once with integration profile; persist returned agent ID and API key outside Git. Avoid overwriting registrations, which invalidates previous credentials.
4. Open `/agents/{agent_id}/connection/ws` using the agent API key and stable connection ID. Adopt the server-returned rooms and cursor. Answer pings with pongs.
5. Process only `message` events with `payload.addressed = true` and verify actor, room and tenant scope.
6. Fetch room context before making an action proposal; correlate to a persistent incident ID.
7. Use `POST /agents/{agent_id}/ops/{operation}` and/or `/agents/{agent_id}/message` for scoped replies. Where required, include `X-Switch-Connection-Id`.
8. Demonstrate real human approval/denial and synthetic execution, independent readback and receipt returned to the same room.
9. Exercise reconnect, duplicates, denial, lost connection, wrong room, wrong actor and verification failure.
10. Record exact Switch release/commit, commands, test logs, timestamps and video during event period.

## Explicit no-go criteria before 3 Nov 2026 13:31 GYT

Do **not** implement or claim the actual hackathon Switch room workflow as pre-event work. Research, dataset preparation, reusable components, and design documentation are allowed; first event integration commit occurs at/after official window opens. No live production device writes, regardless of timing.

## Separation from unrelated tools

This challenge uses **Switch Rooms** documented at `docs.switchagents.ai`, with source `sandbox-quantum/switch`. Do not confuse it with other services named Switch or their unrelated MCP image/video APIs.

## Milestones to implement within official window

1. Switch health check + Mattermost room accessible.
2. Register `ralphiia-incident-triager` with local-only test profile.
3. Event consumption and persistent cursor; first addressed message acknowledged.
4. Human approval correlation and fail-closed gate.
5. Verified synthetic remediation; receipt posted in same room.
6. Reproduce from a fresh clone; complete walkthrough and record demo.
