#!/usr/bin/env python3
"""Small read-only lifecycle canary (no Bellini). Creates ops, simulates completion policy."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inneros_core_runtime import ops_completion_policy as ocp
from inneros_core_runtime import ops_lifecycle_reconciler as olr


def main() -> int:
    read_task = {
        "task_id": "ops_canary_readonly_demo",
        "task_class": "read_only",
        "objective": "rev-parse HEAD",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
    }
    assert ocp.requires_git_commit(read_task) is False
    assert ocp.validate_completed_evidence(read_task, {"summary": "ok", "notes": "sha=x"}) is None
    rec = olr.reconcile_ops_lifecycle(limit=5)
    print(json.dumps({"ok": True, "policy": "read_only_ok", "reconcile": rec}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
