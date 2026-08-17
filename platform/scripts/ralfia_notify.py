#!/usr/bin/env python3
"""Notificaciones RalfIA — Evolution API directo + correo (Swarm IMAP) + coordinación."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import mongo_store, ralfia_time  # noqa: E402
from raphiia_openai.notifications.coordination_alerts import run_coordination_alerts  # noqa: E402
from raphiia_openai.notifications.email_poll import poll_all_mailboxes  # noqa: E402
from raphiia_openai.notifications.evolution_client import (
    any_whatsapp_connected,
    dual_whatsapp_status,
    evolution_available,
)  # noqa: E402
from raphiia_openai.notifications.settings import (  # noqa: E402
    NOTIFY_COORDINATION,
    NOTIFY_EMAIL_POLL,
    NOTIFY_WHATSAPP_TO,
)


def _modules_from_env() -> list | None:
    import os

    raw = os.environ.get("MODULES_HEALTH_JSON", "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def main() -> None:
    ts = ralfia_time.format_log()
    summary: dict = {"ts": ts, "evolution": evolution_available(), "whatsapp_to": NOTIFY_WHATSAPP_TO}
    wa_status = dual_whatsapp_status()
    summary["whatsapp_nodes"] = {
        "primary": {"connected": wa_status.get("primary", {}).get("connected"), "api_up": wa_status.get("primary", {}).get("api_up")},
        "amd": {"connected": wa_status.get("amd", {}).get("connected"), "api_up": wa_status.get("amd", {}).get("api_up")},
    }

    if not evolution_available() and not wa_status.get("amd", {}).get("api_up"):
        summary["error"] = "Evolution API :8082 no responde"
        print(json.dumps(summary, ensure_ascii=False))
        mongo_store.log_coordination(
            agent="NOTIFY",
            summary="Evolution offline — sin WhatsApp",
            event="notify_skip",
            project="ralfia-notifications",
        )
        return

    if not any_whatsapp_connected():
        summary["warning"] = "Ninguna instancia WhatsApp conectada (QR pendiente en Evolution manager)"

    if NOTIFY_EMAIL_POLL:
        email_result = poll_all_mailboxes()
        summary["email"] = email_result
        if email_result.get("alerts_sent"):
            mongo_store.log_coordination(
                agent="NOTIFY",
                summary=f"Email: {email_result.get('alerts_sent')} alertas WhatsApp",
                event="email_alert",
                project="ralfia-notifications",
                metadata=email_result,
            )

    if NOTIFY_COORDINATION:
        coord = run_coordination_alerts(_modules_from_env())
        summary["coordination"] = coord
        if coord.get("whatsapp_sent"):
            mongo_store.log_coordination(
                agent="NOTIFY",
                summary=f"Coord: {coord.get('whatsapp_sent')} WhatsApp enviados",
                event="coord_alert",
                project="ralfia-notifications",
                metadata=coord,
            )

    # Service health is owned by the active/standby dual-node monitor. Keeping a
    # second watcher here produced competing transitions and duplicate alerts.
    # This timer still owns email and coordination polling.
    summary["health_watch"] = {
        "ok": True,
        "delegated_to": "ralfia-dual-node-monitor.service",
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
