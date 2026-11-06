# Real demonstration storyboard (not a video)

**Target:** 2 min 30 s, screen record from real Switch Console and Mattermost; do not use fake evidence, canned chat or synthetic devices for the final hardware demo.

1. **00:00–00:18** Show `#inneros-live-operations` and a real human participant; explain: team chat + Switch + owner-operated agent + Home Assistant.
2. **00:18–00:40** Send an addressed `!lights` or `!state light.<real-id>` to `inneros-incident-triage`. Show the actual HA state and timestamp in the same room.
3. **00:40–01:00** Show code-level boundaries and a denied or missing-approval attempt (no device changes).
4. **01:00–01:35** From a verified human actor, request `!propose light.<real-id> on`. Show the exact action ID and human `!approve` in chat. Keep the device in view when practical. Only do this if the owner has authorized this particular light and no critical load is attached.
5. **01:35–02:00** Verify a new HA GET readback. Show `HA LIVE VERIFIED` only if readback agrees; otherwise honestly show `UNVERIFIED`. State that an HA readback is not a dedicated physical sensor.
6. **02:00–02:30** Show public code and local tests, disclose what existed before the hackathon and what was built Nov 6–7. Include the command `!agents-status` if agent liveness is a concern.

**Never display** Switch or Home Assistant API keys, Mattermost passwords, internal IP addresses, customer names, access logs with auth headers, or private home cameras.

**If unable to reach real Switch:** do not film a mock and label it real. Submit only what is true, or pause rather than misrepresent an unfinished workflow.