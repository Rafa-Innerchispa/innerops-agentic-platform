#!/usr/bin/env python3
"""Alineación cola correo: hygiene, cancel ruido, reprocess intel reciente."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--hygiene-limit", type=int, default=400)
    p.add_argument("--reprocess-days", type=int, default=14)
    p.add_argument("--reprocess-limit", type=int, default=350)
    args = p.parse_args()

    from raphiia_openai.notifications import email_ops_alignment

    result = email_ops_alignment.run_email_ops_alignment(
        dry_run=args.dry_run,
        hygiene_limit=args.hygiene_limit,
        reprocess_days=args.reprocess_days,
        reprocess_limit=args.reprocess_limit,
    )
    print(json.dumps(result, indent=2, default=str)[:12000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
