"""Read-only peer/host observability capabilities for MCP Small (via capability_gateway)."""

from __future__ import annotations

from typing import Any, Callable

from inneros_core_runtime.capability_gateway import register_capability


def _manifest(
    capability_id: str,
    *,
    title: str,
    description: str,
    keywords: list[str],
    mode: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "version": "1.0.0",
        "title": title,
        "domain": "peer_ops",
        "risk_class": "low" if mode == "read_only" else "medium",
        "mode": mode,
        "description": description,
        "keywords": keywords + ["peer", "host", "amd", "intel", "node", "observability"],
        "parameters_schema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
        "required_scopes": ["ralfia:read"] if mode == "read_only" else ["ralfia:agents"],
    }


def _handler(fn: Callable[..., dict[str, Any]]) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    def _wrapped(parameters: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        return fn(**parameters)

    return _wrapped


def register_peer_capabilities() -> int:
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    specs: list[tuple[dict[str, Any], Callable[..., dict[str, Any]]]] = [

        (
            {
                "capability_id": "host.approval.issue.v1",
                "version": "1.0.0",
                "title": "Issue bounded host approval",
                "domain": "peer_ops",
                "risk_class": "medium",
                "mode": "mutation",
                "description": "Issue a short-lived approval scoped to one registered repo/project/node host action.",
                "keywords": ["host", "approval", "owner", "mutation", "deploy"],
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "repo": {"type": "string"},
                        "project_id": {"type": "string"},
                        "node": {"type": "string"},
                        "actor": {"type": "string"},
                        "task_id": {"type": "string"},
                        "correlation_id": {"type": "string"},
                        "ttl_minutes": {"type": "integer"},
                        "reason": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": ["action", "actor", "task_id", "correlation_id"],
                },
                "required_scopes": ["ralfia:agents"],
            },
            _handler(
                lambda **kw: __import__(
                    "inneros_core_runtime.local_execution_plane",
                    fromlist=["issue_host_approval"],
                ).issue_host_approval(**kw)
            ),
        ),
        (
            {
                "capability_id": "peer.infralens.presentation.deploy.v1",
                "version": "1.0.0",
                "title": "Deploy InfraLens judge presentation",
                "domain": "peer_ops",
                "risk_class": "high",
                "mode": "mutation",
                "description": "Deploy only the registered InfraLens MC2 presentation compose on AMD with immutable final-512 verification and automatic rollback.",
                "keywords": ["infralens", "docker", "compose", "deploy", "rollback", "amd", "judge"],
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "node": {"type": "string"},
                        "source_path": {"type": "string"},
                        "expected_sha": {"type": "string"},
                        "approval_id": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": ["source_path", "expected_sha", "approval_id"],
                },
                "required_scopes": ["ralfia:agents"],
            },
            _handler(
                lambda **kw: __import__(
                    "inneros_core_runtime.infralens_hostops",
                    fromlist=["deploy"],
                ).deploy(**kw)
            ),
        ),
        (
            _manifest(
                "peer.route_check.v1",
                title="Peer default route check",
                description="Verify LAN/default route on Intel or AMD without mutating network.",
                keywords=["route", "network", "connectivity"],
                mode="read_only",
                properties={"node": {"type": "string", "description": "primary|amd"}},
            ),
            _handler(ag41.peer_route_check),
        ),
        (
            _manifest(
                "peer.observability_snapshot.v1",
                title="Peer observability snapshot",
                description="Read-only snapshot of ports, processes, disk, memory on a node.",
                keywords=["observability", "snapshot", "status", "health"],
                mode="read_only",
                properties={"node": {"type": "string"}},
            ),
            _handler(ag41.peer_observability_snapshot),
        ),
        (
            _manifest(
                "peer.node_capability_matrix.v1",
                title="Peer node capability matrix",
                description="Symmetric capability matrix for Intel/AMD peer nodes.",
                keywords=["capability", "matrix", "nodes"],
                mode="read_only",
                properties={},
            ),
            _handler(lambda **_kw: ag41.peer_node_capability_matrix()),
        ),
        (
            _manifest(
                "peer.python_runtime.status.v1",
                title="Peer Python runtime status",
                description="Read-only venv/runtime status for a registry-backed project on a node.",
                keywords=["python", "runtime", "venv", "project"],
                mode="read_only",
                properties={
                    "node": {"type": "string"},
                    "project_id": {"type": "string"},
                    "repo": {"type": "string"},
                    "project_path": {"type": "string"},
                },
            ),
            _handler(
                lambda node="primary", project_path="", project_id="", repo="", **_: ag41.peer_python_runtime(
                    node=node,
                    project_path=project_path,
                    project_id=project_id,
                    repo=repo,
                    action="status",
                    dry_run=True,
                )
            ),
        ),
    ]

    for manifest, handler in specs:
        register_capability(manifest, handler)
    return len(specs)