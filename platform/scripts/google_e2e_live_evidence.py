#!/usr/bin/env python3
"""E2E live evidence for ops_75de50f2671d — single correlation_id."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime import gemini_runtime as gr  # noqa: E402

CORRELATION_ID = os.getenv("INNEROS_E2E_CORRELATION_ID", "cursor-google-e2e-20260828")


def main() -> int:
    os.environ.setdefault("INNEROS_GEMINI_MODEL", "gemini-2.5-flash")
    os.environ.setdefault("INNEROS_GEMINI_MODEL_LOCATION", "us-central1")
    os.environ.setdefault("INNEROS_GEMINI_MODEL_LOCATION", "us")
    runtime = gr.InnerOSGeminiRuntime()
    result = runtime.run(
        prompt="Reply with exactly one word: verified",
        correlation_id=CORRELATION_ID,
        allow_external=True,
    )
    evidence = result.get("evidence") or {}
    payload = {
        "correlation_id": CORRELATION_ID,
        "live_mode": result.get("live_mode"),
        "status": result.get("status"),
        "model": result.get("model"),
        "interaction_id": result.get("interaction_id"),
        "verified": evidence.get("verified"),
        "simulated": result.get("simulated"),
        "output_preview": (result.get("output_text") or "")[:120],
        "evidence_keys": sorted(evidence.keys()),
    }
    print(json.dumps(payload, indent=2))
    if result.get("simulated") or result.get("status") == "degraded":
        return 2
    if not evidence.get("verified"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
