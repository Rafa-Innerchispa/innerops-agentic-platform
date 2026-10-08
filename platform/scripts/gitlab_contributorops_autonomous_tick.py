#!/usr/bin/env python3
"""Entrypoint systemd — ciclo autónomo ContributorOps completo."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime.gitlab_contributorops_autonomous_tick import run_autonomous_tick  # noqa: E402


def main() -> int:
    report = run_autonomous_tick()
    print(json.dumps(report, indent=2, default=str)[:16000])
    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
