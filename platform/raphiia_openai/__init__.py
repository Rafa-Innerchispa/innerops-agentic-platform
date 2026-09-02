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

_COMPAT_SUBMODULES = (
    "execution_policy",
)
for _name in _COMPAT_SUBMODULES:
    try:
        _module = importlib.import_module(f"inneros_core_runtime.{_name}")
    except ModuleNotFoundError:
        continue
    globals()[_name] = _module
    sys.modules.setdefault(f"{__name__}.{_name}", _module)

def __getattr__(name: str):
    try:
        module = importlib.import_module(f"inneros_core_runtime.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(name) from exc
    globals()[name] = module
    sys.modules.setdefault(f"{__name__}.{name}", module)
    return module
