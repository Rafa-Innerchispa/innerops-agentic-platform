# Agent instructions for InnerOS Incident Room

1. Read `README.md`, `docs/REUSE_MANIFEST.md`, `docs/SWITCH_INTEGRATION_PLAN.md` and `docs/HACKATHON_BUILD_LOG.md` before proposing changes.
2. **Local-first:** develop with stdlib and local models; do not spend cloud inference credits unless a measured local blocker is documented.
3. **No event-code before official start:** the Switch adapter, room integration and hackathon workflow must be built during the official window and have truthful timestamps.
4. Treat all fixture data as synthetic. Do not connect to CCTV, PBX, alarm, routers, actual Bellini sites or any real network without separate express authorization.
5. Never commit passwords, tokens, `.env`, private keys, customer identifiers, IP maps, CCTV images or secrets. Mask logs.
6. Preserve existing InnerOS core, main branches and production processes. Develop via isolated worktrees and PRs; no forced pushes or blind merges.
7. One change per task, unit tests before commit, CI proof and exact SHA in progress report.
8. Fail closed on uncertain scope, credentials, approval, identity or tenant context. An action ACK is not independent verification.
9. Label `SYNTHETIC`, `PRE-EXISTING`, `HACKATHON-BUILT`, `LIVE-VERIFIED` honestly; never misrepresent mock runs as live integration.
10. Before any Docker action, inspect host RAM, swap and free disk; stop rather than stressing loaded production nodes.
