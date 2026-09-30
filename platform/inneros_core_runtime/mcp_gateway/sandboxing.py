"""MCP Tool Sandboxing and Safety Validator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SandboxCheckResult:
    allowed: bool
    error_code: int = 0
    error_message: str | None = None
    sanitized_args: dict[str, Any] | None = None


# Argument keys commonly holding filesystem paths
PATH_ARG_KEYS = {
    "path",
    "file_path",
    "filepath",
    "target_path",
    "source_path",
    "dest_path",
    "destination_path",
    "cwd",
    "directory",
    "dir_path",
    "folder",
    "repo_path",
    "workspace_path",
    "root_dir",
}

# Operations or keywords considered mutating/write operations
WRITE_OPERATIONS = {
    "write",
    "delete",
    "remove",
    "rm",
    "modify",
    "create",
    "mkdir",
    "touch",
    "exec",
    "execute",
    "run_command",
    "bash",
    "sh",
    "shell",
    "drop",
    "truncate",
}


def is_path_within_roots(path_str: str, allowed_roots: list[str]) -> bool:
    """Check if the normalized path resolves inside one of the allowed roots."""
    try:
        candidate = Path(path_str).resolve()
        for root in allowed_roots:
            root_path = Path(root).resolve()
            if candidate == root_path or root_path in candidate.parents:
                return True
    except Exception:
        return False
    return False


def validate_tool_call_safety(
    tool_name: str,
    arguments: dict[str, Any] | None,
    sandboxing_config: dict[str, Any] | None,
) -> SandboxCheckResult:
    """Validate a tool call against sandboxing configuration (paths and read-only policies)."""
    if not sandboxing_config or not sandboxing_config.get("enabled", False):
        return SandboxCheckResult(allowed=True, sanitized_args=arguments)

    args = arguments or {}
    allowed_paths = sandboxing_config.get("allowed_paths", ["/workspace", "/tmp"])
    read_only = sandboxing_config.get("read_only", False)

    # 1. Check Read-Only Policy
    if read_only:
        name_lower = tool_name.lower()
        if any(w in name_lower for w in WRITE_OPERATIONS):
            return SandboxCheckResult(
                allowed=False,
                error_code=-32002,
                error_message=f"SandboxPolicyViolation: Mutating tool '{tool_name}' blocked under read-only policy.",
            )

    # 2. Check File / Directory Paths in arguments
    for k, v in args.items():
        if isinstance(v, str) and k.lower() in PATH_ARG_KEYS:
            if not is_path_within_roots(v, allowed_paths):
                return SandboxCheckResult(
                    allowed=False,
                    error_code=-32002,
                    error_message=f"SandboxPathViolation: Path '{v}' in parameter '{k}' is outside allowed sandbox paths {allowed_paths}.",
                )

    return SandboxCheckResult(allowed=True, sanitized_args=args)
