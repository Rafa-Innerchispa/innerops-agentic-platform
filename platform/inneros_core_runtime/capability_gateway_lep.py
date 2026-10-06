"""Bridge Local Execution Plane tools into the governed capability_gateway registry."""

from __future__ import annotations

from typing import Any, Callable

from inneros_core_runtime import local_execution_plane as lep
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
    ]

    for manifest, handler in specs:
        register_capability(manifest, handler)
        _LEP_TOOL_SPECS.append((manifest, handler))

    return len(specs)
