"""Legacy notification namespace mapped to inneros_core_runtime.notifications."""

from __future__ import annotations

import importlib
import sys

_canonical = importlib.import_module("inneros_core_runtime.notifications")
__path__ = _canonical.__path__
__all__ = getattr(_canonical, "__all__", [])

for _key, _value in vars(_canonical).items():
    if _key not in {"__name__", "__package__", "__spec__"}:
        globals()[_key] = _value

sys.modules.setdefault(__name__, _canonical)

def __getattr__(name: str):
    try:
        module = importlib.import_module(f"inneros_core_runtime.notifications.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(name) from exc
    globals()[name] = module
    sys.modules.setdefault(f"{__name__}.{name}", module)
    return module
