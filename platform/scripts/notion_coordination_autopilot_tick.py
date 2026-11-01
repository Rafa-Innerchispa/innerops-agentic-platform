#!/usr/bin/env python3
"""Cron: Notion RalfIA Coordination → ops_tasks + HA; luego inbox legacy opcional."""
from __future__ import annotations

import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime import notion_coordination as nc
from inneros_core_runtime import notion_coordination_autopilot as nca


def main() -> int:
    poll = nc.poll_pending_coordination_orders(limit=25)
    legacy_corr = sys.argv[1] if len(sys.argv) > 1 else ""
    legacy = {"ok": True, "skipped": "legacy_inbox_disabled"}
    if legacy_corr:
        legacy = nca.process_notion_inbox_for_cursor(auto_ack=True, correlation_id=legacy_corr)
        legacy["outbox_sync"] = nca.sync_notion_outbox_ack()
    out = {"ok": bool(poll.get("ok")), "notion_poll": poll, "legacy_cursor_inbox": legacy}
    print(out)
    return 0 if poll.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
