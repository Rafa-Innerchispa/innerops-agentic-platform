#!/usr/bin/env python3
"""Periodic coordination hygiene: backlog classify, reclaim, IDE autopilot (system-wide)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

os.environ.setdefault("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core")


def _run_script(name: str) -> dict:
    script = PLATFORM / "scripts" / name
    if not script.is_file():
        return {"ok": False, "skipped": "missing", "script": name}
    proc = subprocess.run(
        [str(PLATFORM / "venv/bin/python3"), str(script)],
        cwd=str(PLATFORM),
        env={**os.environ, "PYTHONPATH": str(PLATFORM)},
        capture_output=True,
        text=True,
        timeout=600,
    )
    return {
        "ok": proc.returncode == 0,
        "script": name,
        "exit_code": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-1000:],
    }


def main() -> int:
    from inneros_core_runtime import dev_swarm_scheduler as dss

    apply = os.getenv("INNEROS_COORDINATION_HYGIENE_APPLY", "1").strip().lower() not in {"0", "false", "no"}
    hygiene = dss.reconcile_coordination_backlog_hygiene(limit=int(os.getenv("COORD_HYGIENE_LIMIT", "300")), dry_run=not apply)
    requeue = dss.requeue_retryable_blocked_ops(limit=int(os.getenv("COORD_REQUEUE_LIMIT", "80")))
    max_c = int(os.getenv("DEV_SWARM_MAX_CONCURRENT", "8"))
    dss.scheduler_start(max_concurrent=max_c, dry_run=False)
    tick = dss.scheduler_tick(limit=int(os.getenv("DEV_SWARM_TICK_LIMIT", "6")), dry_run=False)
    executor = dss.executor_tick(limit=int(os.getenv("DEV_SWARM_EXECUTOR_LIMIT", "2")))
    reclaim = {
        "ok": bool(tick.get("ok")),
        "selected": len(tick.get("selected") or tick.get("started") or []),
        "skipped": len(tick.get("skipped") or []),
        "active_worker_count": tick.get("active_worker_count"),
        "reconcile": tick.get("reconcile"),
        "executed": len(executor.get("executed") or []),
        "executor_skipped": len(executor.get("skipped") or []),
    }
    interactive = _run_script("interactive_provider_autopilot.py")
    cursor = _run_script("cursor_ops_headless_autopilot.py")
    report = {
        "ok": bool(hygiene.get("ok")),
        "hygiene_apply": apply,
        "hygiene": {k: hygiene.get(k) for k in ("reviewed", "action_count", "counts", "dry_run")},
        "requeue": requeue,
        "dev_swarm_tick": {
            "ok": reclaim.get("ok"),
            "stale_workers_reconciled": reclaim.get("stale_workers_reconciled"),
            "active_worker_count": reclaim.get("active_worker_count"),
        },
        "interactive_autopilot": interactive,
        "cursor_autopilot": cursor,
    }
    out = Path(os.environ["INNEROS_CORE_ROOT"]) / "var" / "inneros_autopilot" / "last-coordination-cycle.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
