#!/usr/bin/env python3
"""Genera digest operativo de correo y opcionalmente lo envía por WhatsApp."""
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
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--whatsapp", action="store_true")
    args = p.parse_args()

    from raphiia_openai.notifications import email_owner_digest

    if args.whatsapp:
        result = email_owner_digest.deliver_email_owner_digest(hours=args.hours, limit=args.limit, whatsapp=True)
    else:
        result = email_owner_digest.generate_email_owner_digest(hours=args.hours, limit=args.limit)
    print(result.get("report_text", "")[:8000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
