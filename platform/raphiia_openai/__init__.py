"""Compatibility shim for the legacy ``raphiia_openai`` package name.

The canonical runtime package now lives at ``inneros_core_runtime``. Keep this
shim while older scripts, tests, services, and Mongo metadata still reference
the historical package name.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys

_canonical = importlib.import_module("inneros_core_runtime")

__path__ = _canonical.__path__
__all__ = getattr(_canonical, "__all__", [])

for _key, _value in vars(_canonical).items():
    if _key not in {"__name__", "__package__", "__spec__"}:
        globals()[_key] = _value


class _LegacyAliasFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Resolve ``raphiia_openai.*`` to the canonical module object.

    Sharing only ``__path__`` lets Python execute the same source twice under
    different module names. That splits mocks, singletons, and runtime state.
    The finder imports the canonical child once and registers the legacy name
    as an alias to that exact object.
    """

    legacy_prefix = "raphiia_openai."
    canonical_prefix = "inneros_core_runtime."

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self.legacy_prefix):
            return None
        canonical_name = self.canonical_prefix + fullname[len(self.legacy_prefix):]
        canonical_spec = importlib.util.find_spec(canonical_name)
        if canonical_spec is None:
            return None
        is_package = canonical_spec.submodule_search_locations is not None
        return importlib.util.spec_from_loader(fullname, self, is_package=is_package)

    def create_module(self, spec):
        canonical_name = self.canonical_prefix + spec.name[len(self.legacy_prefix):]
        module = importlib.import_module(canonical_name)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module):
        return None


if not any(isinstance(finder, _LegacyAliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _LegacyAliasFinder())

# Alias the package root as well. Direct imports of legacy child modules are
# handled by the finder above, so both names share one module identity.
sys.modules[__name__] = _canonical
