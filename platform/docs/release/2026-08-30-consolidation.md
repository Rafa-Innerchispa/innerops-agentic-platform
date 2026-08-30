# Release Consolidation Checkpoint - 2026-08-30

Correlation: `inneros-release-consolidation-20260830`

## Purpose

Consolidate the verified platform baseline after the A2A cutover without importing unrelated dirty work from active agents.

## Baseline

- Source runtime commit: `e590ea24f160ab66e60599c238a3ebf842817027`.
- Release branch: `release/inneros-platform-20260830`.
- Release worktree: `/home/rlopez/inneros/inneros_core/worktrees/release-inneros-platform-20260830`.

## Dirty Tree Inventory From Canonical Runtime

Observed in `/home/rlopez/inneros/inneros_core` before release consolidation:

| Classification | Count | Meaning |
|----------------|------:|---------|
| `DISCARD_CANDIDATE` | 929 | Generated worktrees, runtime cache, tmp, backups, or evidence artifacts. Preserve for audit, but do not release from root tree. |
| `KEEP_REVIEW` | 30 | Possible real module/config/service work from other agents. Needs owner/agent confirmation before release. |
| `REVIEW` | 53 | Modified runtime/docs/tests or miscellaneous untracked files needing explicit review. |

No cleanup was performed. The release branch was created in a separate worktree to avoid touching active work.

## Promoted Into This Release

- A2A/Judge/ingest/MI325X approval-gated runtime from commit `e590ea24f160ab66e60599c238a3ebf842817027`.
- `platform/inneros_core_runtime/document_vault.py`, promoted because the clean release import of `mcp_server.py` requires it and the live runtime already depended on it.
- Documentation corrections for canonical InnerOS paths, two-node MCP topology, verified runtime status, and release safety rules.

## Explicitly Not Promoted

- `modules/founderos`, `modules/iskcon-desk`, `modules/visitors`, and other untracked module folders.
- Service unit changes not already in the verified baseline.
- Runtime cache/evidence under `var/`, `tmp/`, generated local execution worktrees, and backup files.
- Workforce product code or deployment surfaces.

## Evidence Required Before Final Release

- Import/probe `mcp_server` from the clean release branch.
- Full platform tests from the clean release branch.
- Fleet status remains consistent across AMD and Intel.
- Report release commit SHA and push result through MCP.
