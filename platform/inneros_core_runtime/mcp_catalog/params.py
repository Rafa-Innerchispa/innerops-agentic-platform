"""Coerción segura de parámetros MCP (evita 'message must be string')."""

from __future__ import annotations

import json
from typing import Any


def as_str(value: Any, field: str, *, default: str = "") -> str:
    if value is None:
        if default:
            return default
        raise ValueError(f"{field} must be a string")
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return as_str(value, "value")


def as_list_str(value: Any, field: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [as_str(v, field) for v in value]
    if isinstance(value, str):
        return [value]
    raise ValueError(f"{field} must be a list of strings")
