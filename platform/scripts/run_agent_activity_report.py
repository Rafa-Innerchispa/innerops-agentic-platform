#!/usr/bin/env python3
"""Genera Agent Activity Report y opcionalmente envía resumen WhatsApp."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--whatsapp", action="store_true")
    args = p.parse_args()

    from raphiia_openai import agent_activity_report

    report = agent_activity_report.generate_agent_activity_report(hours=args.hours)
    print(report.get("report_text", "")[:6000])

    if args.whatsapp:
        try:
            from raphiia_openai.notifications.evolution_client import send_alert_whatsapp
            from raphiia_openai import whatsapp_identity

            text = report.get("report_text", "")[:3500]
            for number in whatsapp_identity.notification_destinations()[:1]:
                send_alert_whatsapp(text, number=number)
        except Exception as exc:
            print(f"whatsapp_error: {exc}", file=sys.stderr)

    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
