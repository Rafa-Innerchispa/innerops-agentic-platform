#!/usr/bin/env python3
"""Reproducible seven-stage demo; fake/dry-run unless live is explicitly gated."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid

from gateway import governed_reboot, verify_recovery
from nebius_client import NebiusNvidiaReasoning


TELEMETRY = {
    "site_id": "site_alpha",
    "device_ref": "ap_validation_01",
    "provider": "unifi",
    "ip": "10.0.1.25",
    "mac": "02:1A:2B:3C:4D:5E",
    "status": "degraded",
    "latency_ms": 280,
    "memory_utilization": 94,
}


def run_demo(*, live_inference: bool = False) -> dict:
    live_authorized = os.environ.get("NEBIUS_LIVE_SMOKE_AUTHORIZED", "") == "1"
    api_key = os.environ.get("NEBIUS_API_KEY", "") if live_inference and live_authorized else ""
    reasoner = NebiusNvidiaReasoning(api_key=api_key, model=os.environ.get("NEBIUS_NVIDIA_MODEL", ""))

    if live_inference and (not live_authorized or not api_key):
        inference = {
            "ok": False,
            "inference_mode": "BLOCKED",
            "error": "live_inference_requires_authorization_and_key",
        }
    else:
        if live_inference:
            reasoner.resolve_live_nvidia_model()
        inference = reasoner.diagnose(TELEMETRY, force_local=not live_inference)

    action = governed_reboot("ap_validation_01", dry_run=True)
    verification = verify_recovery("ap_validation_01", simulation=True)
    evidence_seed = json.dumps(
        {"inference": inference, "action": action, "verification": verification},
        sort_keys=True,
    )
    return {
        "ok": bool(inference.get("ok") and action.get("ok") and verification.get("ok")),
        "workflow_id": f"wf_public_{uuid.uuid4().hex[:12]}",
        "mode": "REAL_INFERENCE_DRY_RUN_ACTION" if live_inference else "FAKE_INFERENCE_DRY_RUN_ACTION",
        "stages": {
            "1_discover": {"evidence_mode": "SIMULATED", "telemetry": TELEMETRY},
            "2_diagnose": inference,
            "3_recommend": inference.get("diagnosis"),
            "4_policy": {"policy": "OWNER_APPROVAL_REQUIRED", "live_mutation_authorized": False},
            "5_execute": action,
            "6_verify": verification,
            "7_evidence": {"sha256": hashlib.sha256(evidence_seed.encode()).hexdigest()},
        },
        "claims": {
            "external_inference_proven": inference.get("inference_mode") == "REAL",
            "physical_mutation_applied": False,
            "physical_recovery_verified": verification.get("verification_mode") == "REAL",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-inference", action="store_true")
    args = parser.parse_args()
    result = run_demo(live_inference=args.live_inference)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
