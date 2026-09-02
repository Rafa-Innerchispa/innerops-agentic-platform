"""Test harness source-of-truth guard for InnerOS platform tests.

Pytest must exercise the checkout/worktree that owns the test files, never an
installed/live copy from /home/rlopez/inneros/inneros_core/platform.
"""

from __future__ import annotations

import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
PLATFORM_TEXT = str(PLATFORM)

sys.path[:] = [item for item in sys.path if item != PLATFORM_TEXT]
sys.path.insert(0, PLATFORM_TEXT)

for prefix in ("raphiia_openai", "inneros_core_runtime"):
    for module_name, module in list(sys.modules.items()):
        if module_name != prefix and not module_name.startswith(prefix + "."):
            continue
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            module_path = Path(module_file).resolve()
        except Exception:
            continue
        if module_path != PLATFORM and PLATFORM not in module_path.parents:
            sys.modules.pop(module_name, None)
