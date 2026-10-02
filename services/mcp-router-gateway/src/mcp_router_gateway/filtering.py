from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Iterable

from .config import ToolProfile
from .errors import SandboxPolicyError, ToolNotAllowedError


def tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("name") or "")


def filter_tools(tools: Iterable[dict[str, Any]], profile: ToolProfile) -> list[dict[str, Any]]:
    allowed = [tool for tool in tools if profile.allows_name(tool_name(tool))]
    if profile.max_tools is not None:
        allowed = allowed[: profile.max_tools]
    return allowed


def extract_tools_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    result = response.get("result") or {}
    tools = result.get("tools")
    if not isinstance(tools, list):
        return []
    return [tool for tool in tools if isinstance(tool, dict)]


def replace_tools_in_response(response: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
    clone = dict(response)
    result = dict(clone.get("result") or {})
    result["tools"] = tools
    clone["result"] = result
    return clone


def allowed_tool_names_from_backend_response(response: dict[str, Any], profile: ToolProfile) -> frozenset[str]:
    return frozenset(tool_name(tool) for tool in filter_tools(extract_tools_from_response(response), profile))


def validate_tool_allowed(tool: str, allowed_names: frozenset[str], profile: ToolProfile) -> None:
    if tool in allowed_names:
        return
    if profile.allow_all and profile.allows_name(tool):
        return
    raise ToolNotAllowedError(f"tool is not allowed by active profile: {tool}", data={"tool": tool, "profile": profile.name})


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _looks_like_path(value: str) -> bool:
    return value.startswith("/") or value.startswith("./") or value.startswith("../")


def _under_allowed_roots(path: str, roots: tuple[str, ...]) -> bool:
    if not path.startswith("/"):
        return True
    normalized = str(PurePosixPath(path))
    for root in roots:
        root_norm = str(PurePosixPath(root))
        if normalized == root_norm or normalized.startswith(root_norm.rstrip("/") + "/"):
            return True
    return False


def validate_sandbox_policy(tool: str, arguments: Any, profile: ToolProfile) -> None:
    prefixes = profile.sandbox.read_only_required_for_prefixes
    if not prefixes or not any(tool.startswith(prefix) for prefix in prefixes):
        return

    text_values = tuple(_iter_strings(arguments))
    for value in text_values:
        if _looks_like_path(value) and not _under_allowed_roots(value, profile.sandbox.allowed_roots):
            raise SandboxPolicyError(
                "path is outside allowed sandbox roots",
                data={"tool": tool, "path": value, "allowed_roots": list(profile.sandbox.allowed_roots)},
            )

    lowered = " ".join(text_values).lower()
    mutating_flags = (" --write", " --delete", " --force", " rm ", " rmdir ", " mv ", " chmod ", " chown ")
    if any(flag in f" {lowered} " for flag in mutating_flags) and "--read-only" not in lowered:
        raise SandboxPolicyError(
            "sensitive tool call appears mutating and lacks --read-only",
            data={"tool": tool},
        )

