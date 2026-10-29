#!/usr/bin/env python3
"""Fail-closed reconcile for verification tasks stuck on no_new_commit_for_task."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import ops_verification_autofinish as ova


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--superseded-by", default="")
    args = parser.parse_args()
    superseded = str(args.superseded_by or "").strip() or None
    results = []
    for tid in args.task_id:
        out = ova.try_fail_verification_no_new_commit(task_id=tid.strip(), superseded_by=superseded)
        results.append(out or {"ok": False, "task_id": tid, "error": "no_result"})
    report = {"ok": all(r.get("ok") for r in results if r), "results": results}
    out_path = ROOT.parent / "var" / "evidence" / "ops_verification_no_commit_reconcile.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({**report, "path": str(out_path)}, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
