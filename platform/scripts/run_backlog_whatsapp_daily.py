#!/usr/bin/env python3
"""AG-57: recordatorio diario WhatsApp con backlog pendiente."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    from inneros_core_runtime.agents import ag57_backlog_steward as ag57

    if ag57._whatsapp_lane_active():
        result = ag57.send_daily_backlog_whatsapp()
    else:
        result = ag57.send_daily_backlog_digest()
    print("ok=", result.get("ok"), "items=", result.get("items"), "chars=", result.get("text_chars"))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
