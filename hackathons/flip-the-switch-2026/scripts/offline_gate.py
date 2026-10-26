#!/usr/bin/env python3
"""Fast, offline-only reproducibility gate for pre-existing synthetic library."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run_gate() -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    stages = {}
    for label, command in (
        ("unit_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]),
        ("secret_pattern_check", [sys.executable, "scripts/preflight.py"]),
    ):
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        stages[label] = {"passed": result.returncode == 0,
                         "summary": (result.stdout + result.stderr)[-3000:]}
    for decision in ("none", "deny", "approve"):
        result = subprocess.run(
            [sys.executable, "-m", "inneros_incident_room.cli", "--decision", decision],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        try:
            value = json.loads(result.stdout)
            actual = value["remediation"]["outcome"]
            final = value["final_state"][value["incident"]["device_alias"]]
            expected = "verified_simulation" if decision == "approve" else "blocked_by_policy"
            expected_state = "healthy" if decision == "approve" else "degraded"
            passed = (result.returncode == 0 and value["fixture_only"] is True
                      and value["switch_connected"] is False
                      and actual == expected and final == expected_state)
            stages[f"fixture_{decision}"] = {"passed": passed,
                                              "outcome": actual, "final_state": final}
        except (ValueError, KeyError, TypeError) as exc:
            stages[f"fixture_{decision}"] = {"passed": False, "error": str(exc),
                                              "stderr": result.stderr[-500:]}
    return {"status": "PASS" if all(s["passed"] for s in stages.values()) else "FAIL",
            "switch_connected": False, "live_device_access": False,
            "validated_at_utc": datetime.now(timezone.utc).isoformat(), "stages": stages}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output")
    args = parser.parse_args(argv)
    report = run_gate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
