# GitHub Professionalization MCP Contract

Status: implementation branch `codex/github-professionalization-automation-20260907`
Correlation: `github-professionalization-automation-20260907`
Task: `ops_9e559e17efa0`

## Tools

- `local_github_professionalization_audit`: read-only matrix for repository metadata, topics, profile, and pinned repositories. It never mutates GitHub.
- `local_github_update_repo_profile`: plans or applies repository description, homepage, and topics. `dry_run` defaults to `true`; apply requires repo permission and policy gates.
- `local_github_update_owner_profile`: plans or applies owner profile fields. Apply requires a server-side GitHub auth token with classic `user` scope.
- `local_github_pin_repositories`: plans or applies additive pinned repositories. It never unpins existing repositories and apply requires classic `user` scope.

## Safety Gates

- Allowed owners are limited by `RALFIA_GITHUB_OWNERS_JSON`; default is `Rafa-Innerchispa`.
- Hackathon/submission-like repositories are blocked for apply unless `freeze_override=true` is explicitly passed by an owner-approved task.
- All mutation tools require `actor`, `task_id`, and `correlation_id` metadata and audit through the local filesystem plane.
- File changes still belong in branch/PR flow; these tools are only for GitHub account/repository metadata.
- No secret is accepted or returned by these tools.

## Dry-run Evidence

Read-only audit on Intel .4 produced `/home/rlopez/inneros/inneros_core/var/evidence/github_professionalization_dryrun_20260908.json`.
Observed: 42 repositories, 24 metadata/topics eligible after freeze policy, 18 freeze-review required, 9 missing description, 34 missing homepage, 42 topicless.
Current scopes: `repo`, `workflow`, `read:org`, `gist`. The minimal missing classic scope for profile and pinned repository writes is `user`.
