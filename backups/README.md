# Local pre-change snapshots

This directory holds timestamped snapshots taken before risky refactors. They may
contain outdated code **and** copied secrets from `.env` at snapshot time.

- Snapshots are **local-only** and listed in the root `.gitignore`.
- Do not `git add` files here. Use `*.example` templates when documenting shape.
- Historical copies may still exist in Git history; see `docs/SECURITY_REMEDIATION_PLAN.md`.
