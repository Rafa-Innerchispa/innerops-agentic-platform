# Switch Console 0.40.1 on Windows: agents visible but silent

**Status:** diagnostic runbook, not a claim that the user's Windows has been inspected. Code and reports remain read-only until the operator explicitly performs a recovery step.

## Situation already confirmed by the participant

- Switch Console v0.40.1 running locally, with Mattermost connected and human account linked.
- Room `inneros-live-operations` exists and shows both the human and `switch-buddy-admin`.
- Agent Providers lists Codex as Installed and Signed in.
- A message addressed to `@switch-buddy-admin` was posted; no agent response seen.
- These observations do **not** establish whether Codex runs successfully or whether Switch's message bridge is healthy.

## First, diagnose without writing anything

1. In Switch Console, send a short message to **switch-buddy-admin direct chat**: `Reply only: READY. Do not run commands.` This separates an agent-controller issue from a Mattermost bridge issue.
2. Check whether the agent appears as running in `Your Agents` and if a session/transcript or error is visible.
3. In PowerShell (no admin elevation), run `./diagnostico_switch_windows.ps1`. The script reports process counts, selected listeners, optional docker status and the number of local watcher records, **without reading auth files**.
4. Read Switch Console logs or status panel *locally* and search for the exact error strings `kill EPERM` and `Bridge ... crashed`. Do not upload logs containing secrets, private IPs or auth headers.

## Two documented upstream Windows issues (6 Nov 2026)

**Issue #1544: agent controller `kill EPERM`.** On Switch Console 0.40.1 with Codex on Windows, agents can appear live and never answer. A user reported a stale watcher PID kept the agent hosts from starting. A **community workaround, not guaranteed to apply**, is:

- Completely quit Switch Console, including its system tray process.
- Only if the log actually shows `kill EPERM`, locate watcher files under `%APPDATA%/switchdash/agent-controller/servers/.../watchers/.../health.json`.
- Back up or rename **only** the affected `health.json` files to `health.json.bak`, retaining their location, and reopen Switch. Never delete the parent directories, sessions, agent configurations or auth files. No bulk reset is authorized.
- Confirm an agent responds in private chat, then retry a room mention.

Source: https://github.com/sandbox-quantum/switch/issues/1544 (5-6 Nov 2026).

**Issue #1510: Mattermost bridge starts too early.** If the direct chat works but the Mattermost room stays silent, check the log for `Bridge ... crashed` after Mattermost startup. The reporter's workaround is `Admin -> Status`, toggle Mattermost off and on **after it is ready**, which restarts the bridge. Do **not** select `Disconnect app` or remove the connector; that risks losing access to existing room state. Verify first in direct chat.

Source: https://github.com/sandbox-quantum/switch/issues/1510 (5 Nov 2026).

Both are real public bugs, **not yet identified as the root cause** on the user's Windows. These actions should only occur after the corresponding symptom is confirmed.

## Acceptance evidence

- A human sends a message in `#inneros-live-operations`.
- A real Switch-managed agent replies within the same room, proving the route Mattermost -> Switch -> agent -> Mattermost.
- Only after this works, register the dedicated InnerOS agent and read live Home Assistant state.
- Only after live readback, and with the owner's explicit approval, operate one allowlisted **light**. No lock/alarm/router/camera actuation.

## Event note

The hackathon deadline is 7 Nov 2026 at 13:29 America/Guayaquil. A live room demo, a reviewed repository and a real video are still required; do not substitute a mock response or claim submission without a receipt.