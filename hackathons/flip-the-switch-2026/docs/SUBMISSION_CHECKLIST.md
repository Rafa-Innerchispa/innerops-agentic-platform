# Owner checklist and release gates

## Before competition (preparation allowed)

- [x] Review official rules, geography, dates and human-only registration requirement.
- [x] Identify existing InnerOS/FieldOps source references.
- [x] Create synthetic fixture and reusable safety/domain contracts; run offline tests.
- [x] Write architecture, provenance manifest and submission plan.
- [ ] Create a dedicated GitHub repository when suitable GitHub repo creation credentials/UI are available; use staging branch only until then.
- [ ] Verify participant has **personally** registered and retained confirmation (no automated registrations).
- [ ] Ensure sufficient local RAM/swap/disk before any optional Switch Docker build; no modifications to loaded production AMD server just for demo.
- [ ] Decide laptop/isolated VM host for Switch; prefer isolated dev system, not production host.

## Work exclusively during hacking window

- [ ] Install/verify actual Switch release; record release version and date.
- [ ] Build and commit new Switch custom agent adapter and chat collaboration workflow.
- [ ] Verify real Switch agent room communications on Mattermost/Discord/etc.
- [ ] Human approval/denial with authenticated actor, correlation, anti-replay checks and fail closed.
- [ ] Synthetic bounded execution + independent verification + evidence receipt in the room.
- [ ] Failure-path tests, reconnection, authorization checks and fresh-clone verification.
- [ ] Publish only scrubbed safe content in dedicated public repository.
- [ ] Record actual demo and screenshots (not generated or staged representations of a live system).
- [ ] Update build log with real timestamps, commit SHAs, truthful status and reusable assets disclosures.
- [ ] Human participant **submits manually** with public repo URL, README and video before deadline.

## Pass criteria

A fresh-clone judge can reproduce a team chat with one person plus one agent communicating through Switch. Denied requests produce no mutation. Approved requests affect only synthetic fixtures, independently verified, with evidence receipts in the same room. Zero secrets. Readme explains what was built **during** the event. All submission materials match facts.

## Official time conversion

Official start: 2026-11-04 00:01 IST (UTC+05:30) = **2026-11-03 13:31** Ecuador (UTC-05:00).
Official deadline: 2026-11-07 23:59 IST (UTC+05:30) = **2026-11-07 13:29** Ecuador (UTC-05:00).
Official kickoff: 2026-11-02 15:30 UTC = **2026-11-02 10:30** Ecuador (UTC-05:00).

Rules: https://www.wemakedevs.org/hackathons/switch/rules
Schedule: https://www.wemakedevs.org/hackathons/switch/schedule
