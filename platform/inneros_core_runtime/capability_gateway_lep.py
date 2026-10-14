"""Bridge Local Execution Plane tools into the governed capability_gateway registry."""

from __future__ import annotations

from typing import Any, Callable

from inneros_core_runtime import local_execution_plane as lep
from inneros_core_runtime import local_gitlab_plane as gl
from inneros_core_runtime.capability_gateway import register_capability

_LEP_TOOL_SPECS: list[tuple[dict[str, Any], Callable[..., dict[str, Any]]]] = []


def _manifest(
    capability_id: str,
    *,
    title: str,
    description: str,
    keywords: list[str],
    mode: str,
    risk_class: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
    required_scopes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "version": "1.0.0",
        "title": title,
        "domain": "local_execution",
        "risk_class": risk_class,
        "mode": mode,
        "description": description,
        "keywords": keywords + ["local execution", "lep", "worktree", "repo", "git"],
        "parameters_schema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
        "required_scopes": required_scopes or ["ralfia:read"],
    }


def _handler(fn: Callable[..., dict[str, Any]]) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    def _wrapped(parameters: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        return fn(**parameters)

    return _wrapped


def _gitlab_manifest(
    capability_id: str,
    *,
    title: str,
    description: str,
    keywords: list[str],
    mode: str,
    risk_class: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
    required_scopes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "version": "1.0.0",
        "title": title,
        "domain": "local_gitlab",
        "risk_class": risk_class,
        "mode": mode,
        "description": description,
        "keywords": keywords + ["gitlab", "contributorops", "merge request", "ci", "pipeline"],
        "parameters_schema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
        "required_scopes": required_scopes or ["ralfia:read"],
    }


def register_local_execution_capabilities() -> int:
    """Register governed LEP capabilities for capability_search/describe/invoke."""
    if _LEP_TOOL_SPECS:
        return len(_LEP_TOOL_SPECS)

    specs: list[tuple[dict[str, Any], Callable[..., dict[str, Any]]]] = [
        (
            _manifest(
                "local_exec.inspect_repo.v1",
                title="Inspect allowlisted repository (read-only)",
                description="Inspect repo policy and checkout metadata without mutations.",
                keywords=["inspect", "repository", "allowlist"],
                mode="read_only",
                risk_class="low",
                properties={"repo": {"type": "string"}},
                required=["repo"],
            ),
            _handler(lep.inspect_repo),
        ),
        (
            _manifest(
                "local_exec.read_worktree_file.v1",
                title="Read allowlisted worktree source file (read-only)",
                description="Return bounded, redacted UTF-8 file content from one governed worktree, without arbitrary shell.",
                keywords=["read", "file", "source code", "inspect contents"],
                mode="read_only",
                risk_class="low",
                properties={
                    "repo": {"type": "string"},
                    "work_branch": {"type": "string"},
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer"},
                },
                required=["repo", "work_branch", "path"],
            ),
            _handler(lep.read_worktree_file),
        ),
        (
            _manifest(
                "local_exec.prepare_repo.v1",
                title="Prepare repository checkout for Dev Swarm",
                description="Fetch and hydrate an owner-approved repo for isolated work.",
                keywords=["prepare", "hydrate", "fetch", "clone"],
                mode="mutation",
                risk_class="medium",
                properties={
                    "repo": {"type": "string"},
                    "base_ref": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                    "remote_url": {"type": "string"},
                },
                required=["repo", "base_ref", "actor", "task_id", "correlation_id", "idempotency_key"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.prepare_repo),
        ),
        (
            _manifest(
                "local_exec.create_worktree.v1",
                title="Create isolated git worktree",
                description="Create a governed worktree on an agent branch prefix.",
                keywords=["worktree", "branch", "isolation"],
                mode="mutation",
                risk_class="medium",
                properties={
                    "repo": {"type": "string"},
                    "base_branch": {"type": "string"},
                    "work_branch": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                required=["repo", "base_branch", "work_branch", "actor", "task_id", "correlation_id"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.create_worktree),
        ),
        (
            _manifest(
                "local_exec.write_file.v1",
                title="Write file inside governed worktree",
                description="Write one file under allowed_paths inside an active worktree.",
                keywords=["write", "file", "patch", "code"],
                mode="mutation",
                risk_class="medium",
                properties={
                    "repo": {"type": "string"},
                    "work_branch": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                required=["repo", "work_branch", "path", "content", "actor", "task_id", "correlation_id"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.write_file),
        ),
        (
            _manifest(
                "local_exec.commit_branch.v1",
                title="Commit worktree changes",
                description="Create a governed git commit on the work branch.",
                keywords=["commit", "git", "branch"],
                mode="mutation",
                risk_class="medium",
                properties={
                    "repo": {"type": "string"},
                    "work_branch": {"type": "string"},
                    "message": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                required=["repo", "work_branch", "message", "actor", "task_id", "correlation_id"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.commit_branch),
        ),
        (
            _manifest(
                "local_exec.run_command_allowlisted.v1",
                title="Run allowlisted command in worktree",
                description="Execute one allowlisted command profile inside the worktree sandbox.",
                keywords=["command", "test", "ruby", "npm", "allowlisted"],
                mode="mutation",
                risk_class="high",
                properties={
                    "repo": {"type": "string"},
                    "work_branch": {"type": "string"},
                    "command": {"type": "array", "items": {"type": "string"}},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "max_output_bytes": {"type": "integer"},
                },
                required=["repo", "work_branch", "command", "actor", "task_id", "correlation_id"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.run_command_allowlisted),
        ),
        (
            _manifest(
                "local_exec.acquire_lock.v1",
                title="Acquire RACB repository lock",
                description="Acquire a coordination lock on an allowlisted repo before mutations.",
                keywords=["lock", "racb", "acquire", "coordination"],
                mode="mutation",
                risk_class="medium",
                properties={
                    "repo": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "ttl_seconds": {"type": "integer"},
                },
                required=["repo", "actor", "task_id", "correlation_id"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.acquire_lock),
        ),
        (
            _manifest(
                "local_exec.release_lock.v1",
                title="Release RACB repository lock",
                description="Release a coordination lock held for an allowlisted repo.",
                keywords=["lock", "racb", "release", "coordination"],
                mode="mutation",
                risk_class="low",
                properties={
                    "repo": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                },
                required=["repo", "actor", "task_id", "correlation_id"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.release_lock),
        ),
        (
            _manifest(
                "local_exec.apply_patch.v1",
                title="Apply unified diff in worktree",
                description="Apply a bounded unified diff patch inside a governed worktree.",
                keywords=["patch", "diff", "apply", "edit"],
                mode="mutation",
                risk_class="medium",
                properties={
                    "repo": {"type": "string"},
                    "work_branch": {"type": "string"},
                    "patch": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                required=["repo", "work_branch", "patch", "actor", "task_id", "correlation_id", "idempotency_key"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.apply_patch),
        ),
        (
            _manifest(
                "local_exec.push_branch.v1",
                title="Push work branch to remote",
                description="Push a validated agent work branch to an allowlisted remote (dry_run default).",
                keywords=["push", "branch", "remote", "git"],
                mode="mutation",
                risk_class="high",
                properties={
                    "repo": {"type": "string"},
                    "work_branch": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                    "remote": {"type": "string"},
                    "dry_run": {"type": "boolean"},
                },
                required=["repo", "work_branch", "actor", "task_id", "correlation_id", "idempotency_key"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.push_branch),
        ),
        (
            _manifest(
                "local_exec.report_evidence.v1",
                title="Report local execution evidence",
                description="Persist a compact evidence event for golden-flow continuity.",
                keywords=["evidence", "report", "checkpoint", "continuity"],
                mode="mutation",
                risk_class="low",
                properties={
                    "repo": {"type": "string"},
                    "work_branch": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "status": {"type": "string"},
                    "evidence": {"type": "object"},
                },
                required=["repo", "work_branch", "actor", "task_id", "correlation_id", "status"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(lep.report_evidence),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.get_merge_request.v1",
                title="Get GitLab merge request (read-only)",
                description="Fetch MR metadata, labels, pipeline summary, and merge status for allowlisted projects.",
                keywords=["mr", "merge request", "inspect", "review", "257991"],
                mode="read_only",
                risk_class="low",
                properties={
                    "project_id_or_path": {"type": "string"},
                    "mr_iid": {"type": "integer"},
                },
                required=["project_id_or_path", "mr_iid"],
            ),
            _handler(gl.get_merge_request),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.list_merge_request_discussions.v1",
                title="List GitLab MR discussions (read-only)",
                description="List human review threads and bot notes on a merge request.",
                keywords=["discussions", "feedback", "review comments", "notes"],
                mode="read_only",
                risk_class="low",
                properties={
                    "project_id_or_path": {"type": "string"},
                    "mr_iid": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                required=["project_id_or_path", "mr_iid"],
            ),
            _handler(gl.list_merge_request_discussions),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.list_merge_request_pipelines.v1",
                title="List GitLab MR pipelines (read-only)",
                description="List CI pipelines attached to a merge request.",
                keywords=["pipelines", "ci status", "tier-1"],
                mode="read_only",
                risk_class="low",
                properties={
                    "project_id_or_path": {"type": "string"},
                    "mr_iid": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                required=["project_id_or_path", "mr_iid"],
            ),
            _handler(gl.list_merge_request_pipelines),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.list_pipeline_jobs.v1",
                title="List GitLab pipeline jobs (read-only)",
                description="List jobs for a pipeline (rubocop, static-analysis, etc.).",
                keywords=["jobs", "failed job", "lint"],
                mode="read_only",
                risk_class="low",
                properties={
                    "project_id_or_path": {"type": "string"},
                    "pipeline_id": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                required=["project_id_or_path", "pipeline_id"],
            ),
            _handler(gl.list_pipeline_jobs),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.get_job_trace.v1",
                title="Get GitLab CI job trace tail (read-only)",
                description="Return bounded, redacted tail of a CI job log for diagnosis.",
                keywords=["trace", "log", "job output", "rubocop failure"],
                mode="read_only",
                risk_class="low",
                properties={
                    "project_id_or_path": {"type": "string"},
                    "job_id": {"type": "integer"},
                    "max_bytes": {"type": "integer"},
                },
                required=["project_id_or_path", "job_id"],
            ),
            _handler(gl.get_job_trace),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.get_issue.v1",
                title="Read GitLab issue and current assignees",
                description="Get issue status, labels, description, assignees and milestone from GitLab.",
                keywords=["issue", "ticket", "assignee", "community contribution"],
                mode="read_only",
                risk_class="low",
                properties={"project_id_or_path": {"type": "string"}, "issue_iid": {"type": "integer"}},
                required=["project_id_or_path", "issue_iid"],
            ),
            _handler(gl.get_issue),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.list_issues.v1",
                title="List GitLab project issues",
                description="List current project issues with optional state and bounded count.",
                keywords=["issues", "backlog", "task discovery"],
                mode="read_only",
                risk_class="low",
                properties={"project_id_or_path": {"type": "string"}, "state": {"type": "string"}, "limit": {"type": "integer"}},
                required=["project_id_or_path"],
            ),
            _handler(gl.list_issues),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.discover_contribution_issues.v1",
                title="Discover public GitLab contribution candidates",
                description="Find open contribution issues with bounded search and labels. Requires independent duplicate checks before claiming.",
                keywords=["contribute", "good first issue", "discover", "community"],
                mode="read_only",
                risk_class="low",
                properties={"search": {"type": "string"}, "labels": {"type": "string"}, "limit": {"type": "integer"}},
            ),
            _handler(gl.discover_contribution_issues),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.list_merge_requests.v1",
                title="List GitLab project merge requests",
                description="List current project merge requests for duplicate and status checks.",
                keywords=["merge requests", "duplicate mr", "review"],
                mode="read_only",
                risk_class="low",
                properties={"project_id_or_path": {"type": "string"}, "state": {"type": "string"}, "limit": {"type": "integer"}},
                required=["project_id_or_path"],
            ),
            _handler(gl.list_merge_requests),
        ),
        (
            _gitlab_manifest(
                "local_gitlab.create_draft_merge_request.v1",
                title="Create GitLab draft merge request",
                description="Open a draft MR on allowlisted GitLab source/target project pairs.",
                keywords=["draft mr", "draft merge", "pull request", "open mr"],
                mode="mutation",
                risk_class="medium",
                properties={
                    "source_project": {"type": "string"},
                    "source_branch": {"type": "string"},
                    "target_project": {"type": "string"},
                    "target_branch": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "dry_run": {"type": "boolean"},
                },
                required=["source_project", "source_branch", "target_project", "title", "description"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(gl.create_draft_merge_request),
        ),
    ]

    for manifest, handler in specs:
        register_capability(manifest, handler)
        _LEP_TOOL_SPECS.append((manifest, handler))

    return len(specs)
