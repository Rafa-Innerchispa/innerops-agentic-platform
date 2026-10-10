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



def _service_action_with_approval(
    *,
    service_id: str,
    node: str = "primary",
    action: str = "restart",
    approval_id: str,
    repo: str = "Rafa-Innerchispa/innerops-agentic-platform",
    project_id: str = "innerops-agentic-platform",
) -> dict[str, Any]:
    from inneros_core_runtime import local_execution_plane as lep
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    scoped_action = f"peer_service_action:{(action or 'restart').strip().lower()}"
    approval = lep.validate_host_approval(
        approval_id=approval_id,
        action=scoped_action,
        repo=repo,
        project_id=project_id,
        node=node,
    )
    if not approval.get("ok"):
        return {"ok": False, "error": "host_approval_invalid", "approval": approval}
    result = ag41.peer_ops_action(service_id=service_id, node=node, action=action, dry_run=False)
    return {**result, "approval": approval}


def _cursor_owner_order(
    *,
    task_id: str = "",
    correlation_id: str = "",
    owner_actor: str = "RAFAEL",
    owner_approved: bool = True,
) -> dict[str, Any]:
    from inneros_core_runtime.cursor_ops_orchestrator import owner_order_execute

    return owner_order_execute(
        task_id=task_id or None,
        correlation_id=correlation_id or None,
        owner_actor=owner_actor,
        channel="capability_gateway",
        owner_approved=owner_approved,
        deliver_cursor_inbox=True,
    )


def register_peer_capabilities() -> int:
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    specs: list[tuple[dict[str, Any], Callable[..., dict[str, Any]]]] = [

        (
            {
                "capability_id": "peer.service.action.v1",
                "version": "1.0.0",
                "title": "Approved peer service action",
                "domain": "peer_ops",
                "risk_class": "high",
                "mode": "mutation",
                "description": "Start/restart/recover an AG-41 allowlisted service only with a matching short-lived host approval.",
                "keywords": ["service", "restart", "recover", "mcp", "systemd", "docker", "approval"],
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "service_id": {"type": "string"},
                        "node": {"type": "string"},
                        "action": {"type": "string"},
                        "approval_id": {"type": "string"},
                        "repo": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["service_id", "approval_id"],
                },
                "required_scopes": ["ralfia:agents"],
            },
            _handler(_service_action_with_approval),
        ),
        (
            {
                "capability_id": "coordination.cursor.owner_order.v1",
                "version": "1.0.0",
                "title": "Owner-authorize and claim Cursor ops task",
                "domain": "coordination",
                "risk_class": "high",
                "mode": "mutation",
                "description": "Invoke the canonical Cursor owner order path directly from compact coordination without relying on WhatsApp inbox parsing.",
                "keywords": ["cursor", "owner", "order", "claim", "authorize", "ops task"],
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "correlation_id": {"type": "string"},
                        "owner_actor": {"type": "string"},
                        "owner_approved": {"type": "boolean"},
                    },
                    "required": [],
                },
                "required_scopes": ["ralfia:agents"],
            },
            _handler(_cursor_owner_order),
        ),

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