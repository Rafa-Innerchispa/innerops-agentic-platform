#!/usr/bin/env python3
"""Ciclo completo correo: poll IMAP → reclasificar inbox → alertas high."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from raphiia_openai.notifications.email_poll import poll_all_mailboxes
    from raphiia_openai.notifications import email_review

    poll = poll_all_mailboxes()
    backfill = email_review.backfill_inbox_reviews(
        limit=2500,
        send_alerts=False,
        reanalyze=True,
    )
    out = {"poll": poll, "backfill": backfill}
    print(json.dumps(out, indent=2, default=str))
    return 0 if poll.get("ok", True) or backfill.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
