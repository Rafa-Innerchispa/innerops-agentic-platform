#!/usr/bin/env python3
"""Run competition Alexa entry for one ops task."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import competition_lane_dispatch as cld


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task-id", required=True)
    args = p.parse_args()
    out = cld.execute_competition_task(args.task_id)
    print(json.dumps(out, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
