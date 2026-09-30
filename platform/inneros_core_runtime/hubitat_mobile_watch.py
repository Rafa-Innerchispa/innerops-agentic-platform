#!/usr/bin/env python3
"""Detecta teléfonos Mobile App Device nuevos en Hubitat y avisa por WhatsApp."""

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

STATE_FILE = Path(os.getenv("HUBITAT_MOBILE_STATE_FILE", "/home/rlopez/data/ralfia/hubitat_mobile_devices.json"))
POLL_SEC = float(os.getenv("HUBITAT_MOBILE_POLL_SEC", "30"))


def _mobile_devices() -> list[dict]:
    listed = hub.list_devices(limit=200)
    if not listed.get("ok"):
        return []
    out = []
    for row in listed.get("devices") or []:
        full = hub.get_device(str(row.get("id")))
        if not full.get("ok"):
            continue
        dev = full.get("device") or {}
        if "mobile app device" not in str(dev.get("type") or "").lower():
            continue
        attrs = full.get("attributes") or {}
        out.append(
            {
                "id": str(dev.get("id")),
                "label": dev.get("label"),
                "presence": attrs.get("presence"),
                "dni": dev.get("dni"),
            }
        )
    return out


def tick() -> dict:
    current = _mobile_devices()
    state = {}
    if STATE_FILE.is_file():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    known = {str(x.get("id")) for x in state.get("devices") or []}
    new = [d for d in current if d["id"] not in known]
    alerts = []
    for device in new:
        msg = f"Nuevo teléfono enlazado en Hubitat Timmy: {device.get('label')} (presencia: {device.get('presence')})."
        alerts.append({"device": device, "whatsapp": send_alert_whatsapp(msg, prefix_node=True)})
    snapshot = {"ts": datetime.now(timezone.utc).isoformat(), "devices": current}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "count": len(current), "new": new, "alerts": alerts, "devices": current}


def run_forever() -> None:
    while True:
        try:
            out = tick()
            if out.get("new"):
                print(json.dumps(out, ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)[:200]}, ensure_ascii=False))
        time.sleep(max(5.0, POLL_SEC))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        run_forever()
    else:
        print(json.dumps(tick(), ensure_ascii=False, indent=2))
