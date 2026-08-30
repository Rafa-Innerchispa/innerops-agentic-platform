# InnerOS Agentic Platform - Agent Instructions

## Canonical Workspace

Use the InnerOS core tree:

```bash
cd /home/rlopez/inneros/inneros_core
```

The old `/home/rlopez/projects/raphiia-openai` path is historical. Do not add new ecosystem services, agents, or runtime code there.

## Coordination First

At the start of each session:

1. Read `get_coordination_live()`.
2. Read your agent inbox.
3. Accept or transfer the relevant ops task before making changes.
4. Use locks/worktrees for development tasks.
5. Report commit SHA, tests, services touched, and blockers back through MCP.

Mongo/live coordination is the source of truth. Markdown inbox mirrors may lag.

## Safety Boundaries

- Preserve other agents' dirty work. Never use `git reset --hard` or broad checkout cleanup unless Rafael explicitly asks for it.
- Do not use broad `rsync --delete` from a dirty platform tree.
- Do not deploy production without review/approval.
- Do not touch Workforce product code, `femar`, `workforce.pcdoctor.ai`, Judge UI, ISKCON UI, OAuth/RBAC visual work, or Cursor-owned tasks unless the accepted task explicitly assigns that surface.
- Keep command execution inside Local Execution Plane allowlists, approved repos, package roots, and typed argv.
- Keep cloud spend gated by explicit owner approval and teardown evidence.

## Current Verified Platform Baseline

- Runtime commit: `e590ea24f160ab66e60599c238a3ebf842817027`.
- A2A bridge: online, 58 agent cards, durable dispatch through InnerOS coordination.
- Fleet: AMD `.5` and Intel `.4` are one logical MCP ecosystem when fingerprints are consistent.
- Judge Console backend: content contract available; UI work is owned separately.
- Drop-folder ingest: `/home/rlopez/data/inneros_ingest`.
- MI325X/DigitalOcean burst: preflight/dry-run and approval gates only by default.
- ROCm10: active vLLM canary service exists; host-level ROCm observed as 7.2.1 during 2026-08-30 consolidation, so do not claim system-wide ROCm10 without a fresh probe.
- Lemonade: `lemonade-lemond.service` observed active.

## Validation

Use the canonical virtualenv when a clean worktree has no local `platform/venv`:

```bash
PYTHONPATH=platform /home/rlopez/inneros/inneros_core/platform/venv/bin/python3 -m pytest -q platform/tests
```
