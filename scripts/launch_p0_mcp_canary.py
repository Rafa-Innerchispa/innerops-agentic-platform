#!/usr/bin/env python3
"""Launch branch MCP with read-only fallback imports from the live checkout.

The repository currently lacks a few modules that exist in the live checkout.
Branch code remains first in package resolution; the live path is consulted only
when a module is absent from the branch. No production file is modified.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH_PLATFORM = ROOT / "platform"
BRANCH_PACKAGE = BRANCH_PLATFORM / "inneros_core_runtime"
LIVE_PACKAGE = Path("/home/rlopez/inneros/inneros_core/platform/inneros_core_runtime")

if not BRANCH_PACKAGE.is_dir():
    raise SystemExit(f"REFUSED: branch runtime package missing: {BRANCH_PACKAGE}")
if not LIVE_PACKAGE.is_dir():
    raise SystemExit(f"REFUSED: live runtime fallback missing: {LIVE_PACKAGE}")

sys.path.insert(0, str(BRANCH_PLATFORM))

import inneros_core_runtime  # noqa: E402

# Preserve branch-first resolution. The production checkout is import-only and
# is never used as a working directory or write target.
inneros_core_runtime.__path__[:] = [str(BRANCH_PACKAGE), str(LIVE_PACKAGE)]

import raphiia_openai  # noqa: E402

raphiia_openai.__path__[:] = list(inneros_core_runtime.__path__)

runpy.run_module("inneros_core_runtime.mcp_server", run_name="__main__", alter_sys=True)
