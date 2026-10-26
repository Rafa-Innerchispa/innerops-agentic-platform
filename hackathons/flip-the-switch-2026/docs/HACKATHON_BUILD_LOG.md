# Hackathon work ledger (append-only intent)

The event organizer explicitly allows existing code but requires that **the Switch setup and competition workflow be built during the hacking window**. Record new work as factual, timestamped entries with commit hashes and evidence. Never backdate.

| Local time (Guayaquil) | Event | Evidence | Status |
| --- | --- | --- | --- |
| 2026-10-22 | Prepared generic reusable incident fixture, tests and documentation | local unit-test output | PRE-EVENT; NOT event submission work |
| 2026-11-03 13:31 or later | First Switch setup/integration | TODO: commit SHA / screenshots / logs | NOT STARTED |
| TBD within event | Mattermost room + real agent traffic | TODO | NOT STARTED |
| TBD within event | Human denies approval and no mutation occurs | TODO | NOT STARTED |
| TBD within event | Human approves synthetic remediation | TODO | NOT STARTED |
| TBD within event | Independent verification + receipt | TODO | NOT STARTED |
| TBD within event | Final fresh-clone replay + video | TODO | NOT STARTED |

### Attribution convention

Use `PRE-EXISTING`, `HACKATHON-BUILT`, `SYNTHETIC`, `CAPTURED-REAL`, or `LIVE-VERIFIED` on material evidence as appropriate. A later commit does not convert earlier code into event-period development.

## 26 October 2026 — direct PRE-EVENT preparation

- The 22 October preparation was recovered into an isolated local workspace without DevSwarm.
- Added generic checksum verification for synthetic evidence, injected synthetic readback failure tests, offline reproducibility gate, and safe checksummed standalone export.
- Unit tests: **24/24 PASS**. Pre-publish pattern check: PASS. Scenarios: unapproved blocked, rejected blocked, approved synthetic only.
- **Pre-existing preparation, NOT hackathon event code:** no Switch agent registration, WebSocket adapter, Mattermost room, live device access, real participant workflow, video or final submission.
- Local Git snapshot and bundle are portable artifacts. A remotely created repository has NOT been claimed.
