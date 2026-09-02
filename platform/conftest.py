"""Pytest bootstrap: always test the current checkout's platform source first.

A developer worktree must never silently import the canonical installed runtime
from another checkout and report PASS/FAIL for code that is not actually under
test.  The bootstrap fixes path precedence and evicts already-loaded stale
InnerOS compatibility modules when they point outside this worktree.
"""
from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parent
platform_text = str(PLATFORM_ROOT)
try:
    sys.path.remove(platform_text)
except ValueError:
    pass
sys.path.insert(0, platform_text)

for module_name, module in list(sys.modules.items()):
    if not (
        module_name == "inneros_core_runtime"
        or module_name.startswith("inneros_core_runtime.")
        or module_name == "raphiia_openai"
        or module_name.startswith("raphiia_openai.")
    ):
        continue
    module_file = getattr(module, "__file__", None)
    if not module_file:
        continue
    try:
        resolved = Path(module_file).resolve()
    except Exception:
        continue
    if not str(resolved).startswith(platform_text):
        sys.modules.pop(module_name, None)
