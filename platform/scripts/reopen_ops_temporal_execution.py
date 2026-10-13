#!/usr/bin/env python3
"""CLI: reopen a terminal Temporal ops workflow generation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime.ops_temporal_recovery import reopen_ops_temporal_execution


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--reason", default="manual_reopen")
    args = parser.parse_args()
    out = reopen_ops_temporal_execution(args.task_id.strip(), reason=args.reason)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
