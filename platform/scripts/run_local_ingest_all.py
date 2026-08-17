#!/usr/bin/env python3
"""Ejecuta ingesta local completa: ChatGPT docs + email VKR + PST."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--email-limit", type=int, default=25)
    p.add_argument("--chatgpt-limit", type=int, default=150)
    args = p.parse_args()

    from raphiia_openai import ingest_pipeline

    result = ingest_pipeline.run_full_local_ingest(
        email_limit=args.email_limit,
        chatgpt_limit=args.chatgpt_limit,
        dry_run=args.dry_run,
    )
    import json

    print(json.dumps(result, indent=2, default=str)[:8000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
