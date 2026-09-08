# MCP Capability Forensics

InnerOS must not normalize MCP tool loss as a new baseline. Before promoting a MCP runtime, compare the candidate catalog with a previous known-good snapshot or Git ref.

## Rules

- `tool_name_present=true` plus missing backend wrapper is a regression.
- Removed tools require `DEPRECATED -> RETIREMENT_PENDING -> OWNER_APPROVED_REMOVAL`.
- Do not auto-update the baseline to silence an alarm.
- Compare capability/tool IDs separately from aliases when a migration introduces a replacement.
- Run candidate/canary checks before restarting the live MCP profile.

## Tools

- `mcp_capability_snapshot`: current catalog plus optional historical union over refs.
- `mcp_capability_diff`: Git ref to Git ref diff with fail-closed issues.
- `mcp_capability_release_gate`: current runtime gate; blocks unapproved removals and declared tools without backend wrappers.

This is a read-only guard. It does not delete evidence, mutate profiles, restart services, or promote deployments by itself.
