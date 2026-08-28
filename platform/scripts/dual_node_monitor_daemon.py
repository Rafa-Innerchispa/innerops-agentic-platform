#!/usr/bin/env python3
"""Active/standby dual-node watchdog. Mongo lease guarantees a single notifier."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path("/home/rlopez/projects/raphiia-openai")
sys.path.insert(0, str(ROOT))

from raphiia_openai.whatsapp_dual_node_monitor import run_monitor_cycle


def main() -> None:
    while True:
        try:
            run_monitor_cycle(notify=True, require_leader=True)
        except Exception:
            # systemd keeps the monitor alive; cycle errors are retried and never expose secrets.
            pass
        time.sleep(30)


if __name__ == "__main__":
    main()
