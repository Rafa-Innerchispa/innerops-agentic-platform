#!/usr/bin/env python3
"""Watcher Hubitat → WhatsApp cuando Multisensor detecta movimiento (AG-32)."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import hubitat_client as hub  # noqa: E402
from raphiia_openai.notifications.evolution_client import send_alert_whatsapp  # noqa: E402

STATE_FILE = Path(os.getenv("HUBITAT_MOTION_STATE_FILE", "/home/rlopez/data/ralfia/hubitat_motion_state.json"))
DEVICE_ID = os.getenv("HUBITAT_MOTION_DEVICE_ID", "4")
POLL_SEC = float(os.getenv("HUBITAT_MOTION_POLL_SEC", "8"))
COOLDOWN_SEC = float(os.getenv("HUBITAT_MOTION_COOLDOWN_SEC", "120"))


def _alert_message(device_id: str) -> str:
    custom = os.getenv("HUBITAT_MOTION_MESSAGE", "").strip()
    if custom and "{sensor}" in custom:
        return custom.format(sensor=hub.display_name(device_id))
    return hub.motion_alert_message(device_id)


def _load_state() -> dict:
    if not STATE_FILE.is_file():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def tick(*, dry_run: bool = False) -> dict:
    if not hub.configured():
        return {"ok": False, "error": "hubitat_not_configured"}
    got = hub.get_attribute(DEVICE_ID, "motion")
    if not got.get("ok"):
        return got
    motion = str(got.get("value") or "").lower()
    label = hub.display_name(DEVICE_ID)
    now = datetime.now(timezone.utc)
    state = _load_state()
    prev = str(state.get("motion") or "").lower()
    last_alert = float(state.get("last_alert_ts") or 0)
    elapsed = now.timestamp() - last_alert
    changed = motion != prev
    should_alert = motion == "active" and changed and elapsed >= COOLDOWN_SEC
    out = {
        "ok": True,
        "device_id": DEVICE_ID,
        "label": label,
        "motion": motion,
        "previous": prev or None,
        "changed": changed,
        "should_alert": should_alert,
        "cooldown_sec": COOLDOWN_SEC,
        "ts": now.isoformat(),
    }
    if should_alert and not dry_run:
        wa = send_alert_whatsapp(_alert_message(DEVICE_ID), prefix_node=True)
        out["whatsapp"] = wa
        if wa.get("ok"):
            state["last_alert_ts"] = now.timestamp()
    state["motion"] = motion
    state["updated_at"] = now.isoformat()
    if not dry_run:
        _save_state(state)
    return out


def run_forever() -> None:
    print(json.dumps({"event": "hubitat_motion_watcher_start", "device_id": DEVICE_ID, "poll_sec": POLL_SEC}, ensure_ascii=False))
    while True:
        try:
            result = tick()
            if result.get("should_alert") or result.get("changed"):
                print(json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)[:200]}, ensure_ascii=False))
        time.sleep(max(3.0, POLL_SEC))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        print(json.dumps(tick(dry_run="--dry-run" in sys.argv), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "--loop":
        run_forever()
    else:
        print(json.dumps(tick(), ensure_ascii=False, indent=2))
