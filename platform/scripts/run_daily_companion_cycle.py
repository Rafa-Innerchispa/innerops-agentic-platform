#!/usr/bin/env python3
"""Timer AG-50: brief diario real y entrega por Echo mediante Home Assistant."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_ECHO = "notify.echo_cuarto_speak"


def main() -> int:
    from raphiia_openai import homeassistant_client as ha
    from raphiia_openai.agents import ag50_daily_companion as ag50

    result = ag50.run_daily_companion("", include_brief=True)
    if not result.get("ok"):
        print("ok=False reason=companion_failed")
        return 1

    message = str(result.get("spoken_brief") or result.get("brief") or "").strip()
    if not message:
        print("ok=False reason=empty_brief")
        return 1

    notify_entity = os.getenv("RALFIA_DAILY_COMPANION_ECHO", DEFAULT_ECHO).strip() or DEFAULT_ECHO
    delivery = ha.call_service(
        "notify",
        "send_message",
        entity_id=notify_entity,
        data={"message": message[:900]},
    )
    print(
        "ok=", bool(delivery.get("ok")),
        "ops=", result.get("open_ops_count"),
        "memory=", result.get("memory_hits"),
        "echo=", notify_entity,
    )
    return 0 if delivery.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
