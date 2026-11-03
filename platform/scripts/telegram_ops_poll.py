#!/usr/bin/env python3
"""Long-poll Telegram getUpdates when webhook is not public."""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import httpx
from inneros_core_runtime import telegram_ops_owner as tg_ops
from inneros_core_runtime.notifications import telegram_client as tg


def main() -> int:
    token = tg._bot_token()
    if not token:
        print("telegram_bot_token_missing", file=sys.stderr)
        return 2
    offset = 0
    while True:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        try:
            r = httpx.get(url, params={"timeout": 50, "offset": offset}, timeout=60.0)
            data = r.json()
        except Exception as exc:
            print("poll_error", exc, file=sys.stderr)
            time.sleep(5)
            continue
        if not data.get("ok"):
            time.sleep(5)
            continue
        for upd in data.get("result") or []:
            offset = int(upd.get("update_id", 0)) + 1
            tg_ops.ingest_telegram_update(upd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
