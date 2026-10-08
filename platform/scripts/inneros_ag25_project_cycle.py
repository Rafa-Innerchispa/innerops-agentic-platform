#!/usr/bin/env python3
"""One AG-25 InnerOS cycle: A2A → Dev Swarm → executor → Integration Guardian (git push) → liveness.

Designed for systemd timer — no ChatGPT session required.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

os.environ.setdefault("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core")


def main() -> int:
    from inneros_core_runtime import autonomous_project_controller as apc
    from inneros_core_runtime.agents import ag42_service_guardian as ag42
    from inneros_core_runtime import dev_swarm_scheduler as dss

    dss.scheduler_start(max_concurrent=int(os.getenv("DEV_SWARM_MAX_CONCURRENT", "4")), dry_run=False)
    gmail_step = None
    if os.getenv("INNEROS_GMAIL_INTEGRATION", "1").strip().lower() not in {"0", "false", "no"}:
        try:
            from inneros_core_runtime.notifications import email_ag25_integration as gmail_ag25

            gmail_step = gmail_ag25.run_gmail_ag25_tick(cycle=0, force_poll=True)
        except Exception as exc:
            gmail_step = {"ok": False, "error": str(exc)[:200]}
    cycle = apc.run_cycle(
        limit=int(os.getenv("AG25_CYCLE_LIMIT", "8")),
        executor_limit=int(os.getenv("AG25_EXECUTOR_LIMIT", "4")),
        dry_run=False,
    )
    heal = None
    if os.getenv("INNEROS_SELF_HEAL_AUTO", "1").strip().lower() not in {"0", "false", "no"}:
        heal = ag42.run_self_heal_cycle(
            auto_repair=True,
            max_repairs=int(os.getenv("INNEROS_SELF_HEAL_MAX", "2")),
        )

    state_dir = Path(os.environ["INNEROS_CORE_ROOT"]) / "var" / "inneros_autopilot"
    state_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "ok": bool(cycle.get("ok")),
        "gmail": gmail_step,
        "cycle": {
            "selected_count": cycle.get("selected_count"),
            "skip_count": cycle.get("skip_count"),
            "active_worker_count": cycle.get("active_worker_count"),
            "guardian_ok": (cycle.get("guardian") or {}).get("ok"),
            "executor_executed": len((cycle.get("executor") or {}).get("executed") or []),
        },
        "self_heal_ok": (heal or {}).get("ok") if heal else None,
        "self_heal_repairs": len((heal or {}).get("repairs") or []) if heal else 0,
    }
    (state_dir / "last-ag25-cycle.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**report, "full_cycle": cycle, "self_heal": heal}, indent=2, default=str)[:12000])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
