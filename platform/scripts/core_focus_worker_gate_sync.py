#!/usr/bin/env python3
"""Sync quality gate modules to Temporal worker release path (msg_b35)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CANONICAL_ROOT = Path(__file__).resolve().parents[1] / "inneros_core_runtime"
RELEASE_ROOT = CANONICAL_ROOT  # legacy: worker must load canonical platform (see apply_canonical_temporal_worker.sh)
FILES = ("temporal_activities.py", "temporal_bounded_executor.py")
BACKUP_DIR = Path("/home/rlopez/inneros/inneros_core/var/evidence/worker_gate_sync_backups")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report: dict = {"ok": True, "timestamp": ts, "files": [], "rollback": []}

    for name in FILES:
        src = CANONICAL_ROOT / name
        dest = RELEASE_ROOT / name
        if not src.is_file():
            report["ok"] = False
            report["files"].append({"name": name, "error": "canonical_missing"})
            continue
        backup = BACKUP_DIR / f"{ts}_{name}"
        if dest.is_file():
            shutil.copy2(dest, backup)
            report["rollback"].append(f"cp {backup} {dest}")
        shutil.copy2(src, dest)
        report["files"].append(
            {
                "name": name,
                "canonical_sha256_16": _sha(src),
                "release_sha256_16_after": _sha(dest),
                "backup": str(backup) if backup.exists() else None,
            }
        )

    restart = subprocess.run(
        ["systemctl", "--user", "restart", "inneros-temporal-worker.service"],
        capture_output=True,
        text=True,
    )
    report["worker_restart"] = {"returncode": restart.returncode, "stderr": (restart.stderr or "")[:500]}
    active = subprocess.run(
        ["systemctl", "--user", "is-active", "inneros-temporal-worker.service"],
        capture_output=True,
        text=True,
    )
    report["worker_active"] = (active.stdout or "").strip()

    # Verify loaded path sees new gate string
    verify = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.util; "
            f"spec=importlib.util.spec_from_file_location('ta', '{RELEASE_ROOT}/temporal_activities.py'); "
            "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
            "print('bridge_artifacts' in open(m.__file__).read())",
        ],
        capture_output=True,
        text=True,
        cwd=str(CANONICAL_ROOT.parent),
    )
    report["release_contains_bridge_gate_marker"] = (verify.stdout or "").strip() == "True"

    out = Path("/home/rlopez/inneros/inneros_core/var/evidence/worker_gate_sync_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") and report.get("worker_active") == "active" else 1


if __name__ == "__main__":
    raise SystemExit(main())
