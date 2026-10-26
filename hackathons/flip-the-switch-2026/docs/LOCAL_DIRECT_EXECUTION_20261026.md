# InnerOS Incident Room: direct local development and recovery

Status: pre-event generic package as of 2026-10-26. The Switch adapter and event workflow do not exist yet. This replaces the failed DevSwarm handoff with repeatable commands that require no agent scheduler, model endpoint, credential or Docker daemon.

## Use the standalone preparation package

From the extracted project root, with Python 3.10+:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python scripts/preflight.py
python scripts/offline_gate.py --output /tmp/incident-room-offline-evidence.json
python scripts/bootstrap_standalone.py --destination /tmp/inneros-incident-room-clean
```

The standalone bootstrap verifies every copied byte with SHA-256, refuses an existing destination, skips Python caches and Git internals, blocks symlinks and aborts when required source files are absent. This addresses the previous test that assumed an unrelated worktree was checked out on the correct branch.

An isolated local Git repository can then be initialized:

```bash
cd /tmp/inneros-incident-room-clean
git init -b main
git add .
git -c user.name="InnerChispa" -c user.email="noreply@example.invalid" commit -m "prep: baseline for Switch event"
```

This is local only. A GitHub remote is not created or pushed by these commands.

## Technical truth

- Existing tests cover generic synthetic incident policy, approved/denied operations, integrity digests and failed readbacks.
- Checksums demonstrate unchanged content only. They are not signatures or tamper-proof records.
- The default synthetic readback observes an in-memory fixture; no actual independent physical telemetry is claimed.
- HumanApproval.actor is untrusted input. The event-period Switch adapter must derive identity and room membership from authenticated Switch events and reject arbitrary chat text as approval.
- No hardware, customer endpoints, live credentials, rented models or paid APIs are contacted.

## Competition constraints

Organizer: https://www.wemakedevs.org/hackathons/switch

Eligible pre-event work: research, documenting, generic reusable libraries, synthetic fixture data, tests, host capacity planning and packaging. The actual Switch installation, adapter and room collaboration must be built during the official hackathon window and committed with truthful dates:

- Start: 2026-11-03 13:31, Ecuador (UTC-5)
- Deadline: 2026-11-07 13:29, Ecuador (UTC-5)

Human registration and official submission are personal acts: no bots. Core production environment, customer cameras and access control are out of scope.

## When the event begins

Choose and record one supported Switch release, use a separate host/container network, connect a real human-managed Mattermost room, implement the custom agent protocol using the current official specification, and run E2E approval/rejection and readback tests against the synthetic device. Capture real logs and a short screen recording. Do not claim this has happened yet.
