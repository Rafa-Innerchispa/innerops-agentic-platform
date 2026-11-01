"""Cursor alias for unified paid headless admission (kept for imports and tests)."""
from __future__ import annotations

from typing import Any

from inneros_core_runtime.ops_headless_execution_policy import (
    MAX_AUTOMATIC_DISPATCHES,
    headless_denial as _headless_denial,
)


def headless_denial(task: dict[str, Any], *, check_budget: bool = True) -> str:
    return _headless_denial(task, provider="cursor", check_budget=check_budget)
