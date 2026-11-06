#!/usr/bin/env python3
"""Reproducible local gate. Doesn't claim live Switch or real HA success."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md", "pyproject.toml", ".env.example",
    "src/inneros_incident_room/switch_event.py",
    "src/inneros_incident_room/live_homeassistant.py",
    "src/inneros_incident_room/inneros_live.py",
    "scripts/register_agent.py", "scripts/run_live_homeassistant.py",
    "scripts/discover_ha_lights.py", "scripts/diagnostico_switch_windows.ps1",
    "scripts/preflight_windows.ps1", "docs/SWITCH_DIAGNOSIS_20261106.md",
]

def main() -> int:
    checks = {}
    missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
    checks["required_files"] = {"ok": not missing, "missing": missing}
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    for label, cmd in [
        ("unit_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]),
        ("basic_secret_scan", [sys.executable, "scripts/preflight.py"]),
    ]:
        process = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, timeout=60)
        checks[label] = {"ok": process.returncode == 0,
                         "output_tail": (process.stdout + process.stderr)[-1400:]}
    report = {
        "project": "InnerOS Incident Room",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "local_code_gate": "PASS" if all(c["ok"] for c in checks.values()) else "FAIL",
        "live_switch_verified": False,
        "live_home_assistant_verified": False,
        "recorded_real_demo": False,
        "organizer_submission_confirmed": False,
        "checks": checks,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["local_code_gate"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())