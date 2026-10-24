from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from demo_runner import run_demo
from gateway import governed_poe_cycle, governed_reboot, verify_recovery
from nebius_client import NebiusNvidiaReasoning, TelemetrySanitizer


def test_public_demo_is_truthfully_fake_by_default():
    result = run_demo(live_inference=False)
    assert result["ok"] is True
    assert result["mode"] == "FAKE_INFERENCE_DRY_RUN_ACTION"
    assert result["claims"] == {
        "external_inference_proven": False,
        "physical_mutation_applied": False,
        "physical_recovery_verified": False,
    }


def test_public_live_actions_fail_closed_without_adapter():
    reboot = governed_reboot(
        "ap_01", dry_run=False, approval_token="approved", approval_validated=True
    )
    poe = governed_poe_cycle(
        "switch_01", 4, dry_run=False, approval_token="approved", approval_validated=True
    )
    assert reboot["error"] == "provider_adapter_unavailable"
    assert poe["error"] == "provider_adapter_unavailable"
    assert reboot["mutation_applied"] is False
    assert poe["mutation_applied"] is False


def test_public_recovery_distinguishes_simulated_and_unverified():
    simulated = verify_recovery("ap_01", simulation=True)
    unverified = verify_recovery("ap_01")
    assert simulated["verification_mode"] == "SIMULATED"
    assert unverified["verification_mode"] == "NOT_VERIFIED"
    assert unverified["recovered"] is False


def test_public_sanitizer_removes_secret_and_private_identifiers():
    sanitized, count = TelemetrySanitizer.sanitize({
        "ip": "172.20.1.5",
        "mac": "AA:BB:CC:DD:EE:FF",
        "password": "top-secret",
        "authorization": "credential-fragment-for-test",
    })
    serialized = json.dumps(sanitized)
    assert "172.20.1.5" not in serialized
    assert "AA:BB:CC:DD:EE:FF" not in serialized
    assert "top-secret" not in serialized
    assert "credential-fragment-for-test" not in serialized
    assert count == 2


def test_public_reasoner_without_key_is_explicit_local_heuristic():
    result = NebiusNvidiaReasoning(api_key="", model="").diagnose({"device_ref": "ap_01"})
    assert result["inference_mode"] == "LOCAL_HEURISTIC"
    assert result["provider_receipt"]["evidence_mode"] == "NOT_RUN"
