#!/usr/bin/env python3
"""Prueba AG-55: Gmail app passwords + import bóveda owner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import owner_vault  # noqa: E402
from raphiia_openai.agents import ag55_browser_ops_agent as ag55  # noqa: E402


def main() -> None:
    print("=== 1) Import credenciales → bóveda cifrada ===")
    imp = owner_vault.import_email_accounts_to_vault()
    summary = owner_vault.get_owner_vault_summary()
    print(json.dumps({"import": imp, "summary": summary}, indent=2, ensure_ascii=False))

    print("\n=== 2) AG-55 dry_run Gmail app passwords ===")
    dry = ag55.agent_browser_run_task(
        "screenshot",
        "https://myaccount.google.com/apppasswords",
        profile="rafagye_gmail",
        dry_run=True,
    )
    print(json.dumps(dry, indent=2, ensure_ascii=False))

    print("\n=== 3) AG-55 screenshot real (headless) ===")
    real = ag55.agent_browser_run_task(
        "screenshot",
        "https://myaccount.google.com/apppasswords",
        profile="rafagye_gmail",
        dry_run=False,
        timeout_ms=45000,
    )
    safe = {k: v for k, v in real.items() if k not in ("text",)}
    print(json.dumps(safe, indent=2, ensure_ascii=False))
    if real.get("text"):
        print("extract_preview:", str(real["text"])[:300])


if __name__ == "__main__":
    main()
