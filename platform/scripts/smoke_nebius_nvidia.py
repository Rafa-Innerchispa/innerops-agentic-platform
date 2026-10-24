#!/usr/bin/env python3
"""Reproducible, secret-safe Nebius × NVIDIA smoke test.

Fake mode is the default.  A billable live request requires all three gates:
``--live``, ``NEBIUS_LIVE_SMOKE_AUTHORIZED=1``, and a server-side vault key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime.nebius_nvidia_reasoning import (
    NebiusNvidiaReasoning,
    load_nebius_api_key_from_vault,
)


SMOKE_TELEMETRY = {
    "site_id": "site_alpha",
    "device_ref": "ap_validation_01",
    "provider": "unifi",
    "offline": True,
    "latency_ms": 180,
    "memory_utilization": 91,
}


def run_smoke(*, live: bool = False) -> dict[str, Any]:
    if not live:
        diagnosis = NebiusNvidiaReasoning(api_key="", model="").diagnose(
            SMOKE_TELEMETRY,
            force_local=True,
        )
        return {
            "ok": True,
            "mode": "FAKE",
            "external_inference": {
                "status": "BLOCKED_NOT_AUTHORIZED",
                "reason": "Pass --live and set NEBIUS_LIVE_SMOKE_AUTHORIZED=1.",
            },
            "diagnosis": diagnosis,
            "secret_printed": False,
        }

    if os.environ.get("NEBIUS_LIVE_SMOKE_AUTHORIZED", "").strip() != "1":
        return {
            "ok": False,
            "mode": "BLOCKED",
            "error": "external_credit_authorization_required",
            "secret_printed": False,
        }

    api_key, source_ref = load_nebius_api_key_from_vault()
    if not api_key:
        return {
            "ok": False,
            "mode": "BLOCKED",
            "error": "nebius_vault_key_unavailable",
            "accepted_sources": ["owner_vault:nebius_token_factory/api_key", "owner_vault:nebius/api_key"],
            "secret_printed": False,
        }

    reasoner = NebiusNvidiaReasoning(
        api_key=api_key,
        model=os.environ.get("NEBIUS_NVIDIA_MODEL", "").strip(),
    )
    selected_model = reasoner.resolve_live_nvidia_model()
    diagnosis = reasoner.diagnose(SMOKE_TELEMETRY)
    return {
        "ok": diagnosis.get("inference_mode") == "REAL",
        "mode": "REAL" if diagnosis.get("inference_mode") == "REAL" else "BLOCKED",
        "credential_source": source_ref,
        "model": selected_model,
        "provider_receipt": diagnosis.get("provider_receipt"),
        "diagnosis": diagnosis.get("diagnosis"),
        "sanitization": diagnosis.get("sanitization"),
        "secret_printed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use authorized Token Factory inference")
    args = parser.parse_args()
    result = run_smoke(live=args.live)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
