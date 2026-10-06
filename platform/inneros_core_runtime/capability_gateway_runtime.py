"""Project Runtime Registry capabilities for MCP Small golden flow."""

from __future__ import annotations

from typing import Any, Callable

from inneros_core_runtime import project_runtime_registry as prr
from inneros_core_runtime.capability_gateway import register_capability


def _manifest(
    capability_id: str,
    *,
    title: str,
    description: str,
    keywords: list[str],
    mode: str,
    properties: dict[str, Any],
    required: list[str],
    required_scopes: list[str],
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "version": "1.0.0",
        "title": title,
        "domain": "project_runtime",
        "risk_class": "medium" if mode == "mutation" else "low",
        "mode": mode,
        "description": description,
        "keywords": keywords + ["project runtime", "bootstrap", "host", "node"],
        "parameters_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
        "required_scopes": required_scopes,
    }


def _handler(fn: Callable[..., dict[str, Any]]) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    def _wrapped(parameters: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        return fn(**parameters)

    return _wrapped


def register_project_runtime_capabilities() -> int:
    specs = [
        (
            _manifest(
                "project_runtime.resolve.v1",
                title="Resolve registered project runtime path",
                description="Resolve project_id/repo to governed node path from the runtime registry.",
                keywords=["resolve", "registry", "path"],
                mode="read_only",
                properties={
                    "project_id": {"type": "string"},
                    "repo": {"type": "string"},
                    "node": {"type": "string"},
                },
                required=[],
                required_scopes=["ralfia:read"],
            ),
            _handler(prr.resolve_project),
        ),
        (
            _manifest(
                "project_runtime.bootstrap.v1",
                title="Bootstrap project runtime on node",
                description="Plan or apply safe git bootstrap for a registered project on Intel/AMD.",
                keywords=["bootstrap", "clone", "fetch"],
                mode="mutation",
                properties={
                    "node": {"type": "string"},
                    "project_id": {"type": "string"},
                    "repo": {"type": "string"},
                    "remote_url": {"type": "string"},
                    "base_ref": {"type": "string"},
                    "expected_sha": {"type": "string"},
                    "actor": {"type": "string"},
                    "task_id": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "dry_run": {"type": "boolean"},
                },
                required=["project_id"],
                required_scopes=["ralfia:agents"],
            ),
            _handler(prr.bootstrap_runtime),
        ),
    ]
    for manifest, handler in specs:
        register_capability(manifest, handler)
    return len(specs)
