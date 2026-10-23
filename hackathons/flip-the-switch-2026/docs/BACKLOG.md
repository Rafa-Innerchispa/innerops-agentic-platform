# Implementation issue backlog

All 'event implementation' issues can be planned before the competition, but their integration code and workflow execution must be developed inside the event window.

| Priority | Work item | Acceptance proof | Phase |
| --- | --- | --- | --- |
| P0 | Repository governance and secrets scrub | New repo link, main protection, public-safe audit | preparation |
| P0 | Confirm host capacity and Switch release | isolated-host metrics; no production mutation | preparation |
| P0 | Custom Switch WS/HTTP adapter | real addressed message in Switch room | event only |
| P0 | Human approval and denial from verified Switch room actor | denied leaves synthetic state unchanged | event only |
| P0 | Correlation, duplicate-event and reconnect handling | repeat/replay test pass | event only |
| P0 | Synthetic verifier and receipt posted to same Switch room | action/approval/verification evidence | event only |
| P0 | Reproducibility/CI test from fresh checkout | install + smoke passing with event commit | event only |
| P0 | 2–3m real demo, screenshots and manual submission | shareable video/repo, organizer receipt | event only |
| P1 | Second specialist agent in room | second agent evaluates triage with trace | event only |
| P1 | Blog and social update | factual walkthrough, no customer details | after proof |
| P2 | Production Bellini integration | separate client approval and security review | explicitly OUT OF SCOPE |
