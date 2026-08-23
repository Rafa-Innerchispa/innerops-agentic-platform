"""Compatibility shim for the legacy ``raphiia_openai`` package name.

The canonical runtime package now lives at ``inneros_core_runtime``.  Keep this
shim while older scripts, tests, services, and Mongo metadata still reference
the historical package name.
"""

from __future__ import annotations

import importlib
import sys

_canonical = importlib.import_module("inneros_core_runtime")

__path__ = _canonical.__path__
__all__ = getattr(_canonical, "__all__", [])

for _key, _value in vars(_canonical).items():
    if _key not in {"__name__", "__package__", "__spec__"}:
        globals()[_key] = _value

sys.modules.setdefault(__name__, _canonical)
