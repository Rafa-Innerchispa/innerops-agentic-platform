#!/usr/bin/env python3
"""Watchdog cada minuto: gateway :5188 + túnel ngrok público.

Prioridad: recuperar gateway zombie (causa típica de 502 ERR_NGROK_8012).
No reinicia ngrok si el túnel local está sano y solo fallaba el backend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import ngrok_watch, ralfia_time  # noqa: E402
from raphiia_openai import mongo_store  # noqa: E402


def main() -> int:
    gw = ngrok_watch.check_public_gateway()
    ng = ngrok_watch.check_ngrok_tunnel()
    summary: dict = {
        "ts": ralfia_time.format_log(),
        "gateway": gw.get("status"),
        "ngrok": ng.get("status"),
        "external_http": ng.get("external_http"),
    }

    need = gw.get("status") != "up" or ng.get("status") != "up"
    if not need:
        summary["action"] = "none"
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    rec = ngrok_watch.try_recover_ngrok()
    summary["recover"] = {
        "ok": rec.get("ok"),
        "action": rec.get("action"),
        "after_ngrok": (rec.get("after") or {}).get("status"),
        "after_gateway": ((rec.get("gateway_recover") or {}).get("after") or {}).get("status"),
    }
    print(json.dumps(summary, ensure_ascii=False))

    if not rec.get("ok"):
        try:
            mongo_store.log_coordination(
                agent="WATCHDOG",
                summary=(
                    f"public HTTPS recover FAIL gateway={gw.get('status')} "
                    f"ngrok={ng.get('status')} action={rec.get('action')}"
                )[:300],
                event="public_https_watchdog_fail",
                project="raphiia-openai",
                metadata=summary,
            )
        except Exception:
            pass
        return 1

    if rec.get("action") and rec.get("action") != "none":
        try:
            mongo_store.log_coordination(
                agent="WATCHDOG",
                summary=f"public HTTPS recovered: {rec.get('action')}"[:300],
                event="public_https_watchdog_ok",
                project="raphiia-openai",
                metadata=summary,
            )
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
