#!/usr/bin/env python3
"""Cross-test coordinación sin aprobación WhatsApp (env INNEROS_COORD_AUTO_OWNER_APPROVE=1).

Ejecuta: quad-lane rev-parse, parada identidad (externos + carriles), golden canary acotado.
Escribe reporte JSON en var/evidence/coordination_cross_test_report.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT.parent / "var" / "evidence" / "coordination_cross_test_report.json"
VENV_PY = ROOT / "venv" / "bin" / "python3"
PY = str(VENV_PY if VENV_PY.is_file() else Path(sys.executable))

ENV = {
    **os.environ,
    "PYTHONPATH": str(ROOT),
    "INNEROS_COORD_AUTO_OWNER_APPROVE": "1",
    "NOTIFY_OPS_CREATE_AUTH": "0",
    "NOTIFY_OPS_INTERNAL_CREATE": "0",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(script: str, *args: str, timeout: int = 600) -> dict:
    cmd = [PY, str(ROOT / "scripts" / script), *args]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=ENV, capture_output=True, text=True, timeout=timeout)
    dt = time.perf_counter() - t0
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    parsed: dict | list | None = None
    if out:
        try:
            parsed = json.loads(out.splitlines()[-1] if out.startswith("{") else out)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(out[out.rfind("{") :])
            except json.JSONDecodeError:
                parsed = None
    return {
        "script": script,
        "args": list(args),
        "returncode": proc.returncode,
        "seconds": round(dt, 2),
        "ok": proc.returncode == 0,
        "json_tail": parsed,
        "stderr_tail": err[-1500:] if err else "",
        "stdout_tail": out[-2000:] if out and parsed is None else "",
    }


def main() -> int:
    run_id = f"cross_{uuid.uuid4().hex[:10]}"
    report: dict = {
        "ok": True,
        "run_id": run_id,
        "started_at": _utc(),
        "env_flags": {
            "INNEROS_COORD_AUTO_OWNER_APPROVE": "1",
            "NOTIFY_OPS_CREATE_AUTH": "0",
        },
        "phases": [],
    }

    phases = [
        ("quad_lane_canary", "ops_quad_lane_canary.py", ["--mode", "orchestrate", "--correlation-id", f"{run_id}-quad"], 900),
        ("identity_parade_full", "agent_identity_parade_sequential.py", [], 3600),
        ("golden_canary", "core_focus_golden_canary_e2e.py", [], 600),
    ]

    for name, script, args, timeout in phases:
        entry = {"name": name, "started_at": _utc()}
        try:
            entry["result"] = _run(script, *args, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            entry["result"] = {"ok": False, "error": "timeout", "script": script, "partial": str(exc)[:200]}
        entry["finished_at"] = _utc()
        report["phases"].append(entry)
        if not entry["result"].get("ok"):
            report["ok"] = False
            if name == "identity_parade_full":
                # parada larga: continuar con golden aunque falle parcial
                continue
            break

    report["finished_at"] = _utc()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
