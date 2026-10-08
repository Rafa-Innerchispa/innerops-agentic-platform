#!/usr/bin/env python3
"""Cron-friendly: Notion↔Cursor autopilot + outbox ACK."""
from __future__ import annotations

import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime import notion_coordination_autopilot as nca

if __name__ == "__main__":
    corr = sys.argv[1] if len(sys.argv) > 1 else "inneros-core-autonomy-model-pin-20261008"
    out = nca.process_notion_inbox_for_cursor(auto_ack=True, correlation_id=corr)
    out["outbox_sync"] = nca.sync_notion_outbox_ack()
    print(out)
