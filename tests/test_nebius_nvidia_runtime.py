"""Comprehensive test suite for Nebius x NVIDIA Physical AI Runtime & Governed Capabilities.

Covers:
1. Capability Gateway registration & discovery (reboot, poe_cycle, verify_recovery)
2. Approval gating: live mutations fail closed without owner authorization
3. Dry-run safety: simulations report staged plans without physical impact
4. Idempotency and evidence receipts
5. UniFi and Grandstream GWN provider handlers
6. Honest provider gap reporting for unsupported features and vendors
7. Post-reboot recovery verification
8. Preserving existing read-only query capabilities
9. Telemetry sanitization (no customer names, private IPs, or MACs sent to cloud)
10. Nebius x NVIDIA reasoning adapter (mocked API call)
11. Local fallback reasoning (offline / no external credits)
12. End-to-end 7-stage bounded Physical AI workflow
"""

import json
import sys
from pathlib import Path
from unittest import mock
import pytest

_PLATFORM_DIR = Path(__file__).resolve().parent.parent / "platform"
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))
import inneros_core_runtime
_INNEROS_PKG = _PLATFORM_DIR / "inneros_core_runtime"
if str(_INNEROS_PKG) not in inneros_core_runtime.__path__:
    inneros_core_runtime.__path__.insert(0, str(_INNEROS_PKG))

from inneros_core_runtime.capability_gateway import (
    capability_describe,
    capability_execution,
    capability_invoke,
    capability_search,
)
from inneros_core_runtime.nebius_nvidia_reasoning import (
    NebiusNvidiaReasoning,
    TelemetrySanitizer,
    run_physical_ai_workflow,
)


def test_persistent_capabilities_registered():
    """Verify reboot, poe_cycle, and verify_recovery capabilities are registered."""
    reboot = capability_describe("network.device.reboot.v1")
    assert reboot["ok"] is True
    assert reboot["capability"]["mode"] == "mutation"
    assert reboot["capability"]["risk_class"] == "high"

    poe = capability_describe("network.device.poe_cycle.v1")
    assert poe["ok"] is True
    assert poe["capability"]["mode"] == "mutation"
    assert poe["capability"]["risk_class"] == "critical"

    verify = capability_describe("network.device.verify_recovery.v1")
    assert verify["ok"] is True
    assert verify["capability"]["mode"] == "read_only"


def test_capability_search_finds_new_capabilities():
    """Verify search index returns the newly registered capabilities."""
    search_res = capability_search(query="network reboot")
    assert search_res["ok"] is True
    cap_ids = [c["capability_id"] for c in search_res["capabilities"]]
    assert "network.device.reboot.v1" in cap_ids

    search_poe = capability_search(query="poe cycle")
    assert search_poe["ok"] is True
    cap_ids_poe = [c["capability_id"] for c in search_poe["capabilities"]]
    assert "network.device.poe_cycle.v1" in cap_ids_poe


def test_reboot_requires_approval_when_live():
    """Live reboot (dry_run=False) fails closed without owner approval."""
    res = capability_invoke(
        capability_id="network.device.reboot.v1",
        parameters={
            "device_ref": "test_ap_01",
            "dry_run": False,
        },
    )
    assert res["ok"] is False
    assert res["status"] == "FAILED"
    assert res["result"]["error"] == "approval_required"
    assert res["result"]["requires_approval"] is True
    assert res["result"]["evidence_receipt"]["status"] == "BLOCKED_APPROVAL_REQUIRED"


def test_poe_cycle_requires_approval_when_live():
    """Live PoE cycle (dry_run=False) fails closed without owner approval."""
    res = capability_invoke(
        capability_id="network.device.poe_cycle.v1",
        parameters={
            "switch_ref": "test_sw_01",
            "port": 4,
            "dry_run": False,
        },
    )
    assert res["ok"] is False
    assert res["status"] == "FAILED"
    assert res["result"]["error"] == "approval_required"
    assert res["result"]["requires_approval"] is True


def test_reboot_dry_run_safety():
    """Dry-run reboot stages the action without modifying hardware."""
    res = capability_invoke(
        capability_id="network.device.reboot.v1",
        parameters={
            "device_ref": "test_ap_01",
            "provider": "unifi",
            "dry_run": True,
        },
    )
    assert res["ok"] is True
    assert res["status"] == "COMPLETED"
    assert res["result"]["dry_run"] is True
    assert res["result"]["status"] == "STAGED_DRY_RUN"
    assert res["result"]["mutation_applied"] is False
    assert "plan" in res["result"]
    assert res["result"]["evidence_receipt"]["dry_run"] is True


def test_poe_cycle_dry_run_safety():
    """Dry-run PoE cycle validates parameters and stages port cycle."""
    res = capability_invoke(
        capability_id="network.device.poe_cycle.v1",
        parameters={
            "switch_ref": "usw_pro_24",
            "port": 12,
            "provider": "unifi",
            "dry_run": True,
        },
    )
    assert res["ok"] is True
    assert res["result"]["status"] == "STAGED_DRY_RUN"
    assert res["result"]["port"] == 12
    assert res["result"]["mutation_applied"] is False


def test_reboot_live_with_valid_approval_still_requires_adapter():
    """Approval is necessary but cannot substitute for a real provider adapter."""
    res = capability_invoke(
        capability_id="network.device.reboot.v1",
        parameters={
            "device_ref": "test_ap_01",
            "provider": "unifi",
            "dry_run": False,
            "approval_token": "owner_approved_token_12345",
        },
        context={"owner_approved": True},
    )
    assert res["ok"] is False
    assert res["status"] == "FAILED"
    assert res["result"]["error"] == "provider_adapter_unavailable"
    assert res["result"]["mutation_applied"] is False


def test_arbitrary_nonempty_approval_token_is_rejected():
    res = capability_invoke(
        capability_id="network.device.reboot.v1",
        parameters={
            "device_ref": "test_ap_01",
            "provider": "unifi",
            "dry_run": False,
            "approval_token": "any-string-is-not-proof",
        },
    )
    assert res["ok"] is False
    assert res["result"]["error"] == "approval_required"


def test_poe_cycle_live_with_valid_approval_still_requires_adapter():
    """An approved PoE cycle fails closed when no live adapter is connected."""
    res = capability_invoke(
        capability_id="network.device.poe_cycle.v1",
        parameters={
            "switch_ref": "usw_agg_01",
            "port": 8,
            "provider": "unifi",
            "dry_run": False,
            "owner_approved": True,
        },
        context={"owner_approved": True},
    )
    assert res["ok"] is False
    assert res["result"]["error"] == "provider_adapter_unavailable"
    assert res["result"]["mutation_applied"] is False


def test_reboot_live_requires_real_provider_receipt_and_redacts_secrets():
    """A connected adapter may prove execution; its receipt is sanitized."""
    def executor(**_kwargs):
        return {
            "ok": True,
            "provider_receipt": {
                "evidence_mode": "REAL",
                "request_id": "unifi-request-123",
                "api_token": "must-never-reach-evidence",
            },
        }

    res = capability_invoke(
        capability_id="network.device.reboot.v1",
        parameters={
            "device_ref": "test_ap_01",
            "provider": "unifi",
            "dry_run": False,
            "approval_token": "owner-approved",
        },
        context={"owner_approved": True, "network_action_executor": executor},
    )
    assert res["ok"] is True
    assert res["result"]["mutation_applied"] is True
    receipt_json = json.dumps(res["result"]["evidence_receipt"])
    assert "must-never-reach-evidence" not in receipt_json
    assert "[REDACTED]" in receipt_json


def test_honest_provider_gap_for_gwn_poe_cycle():
    """Grandstream GWN Cloud does not support PoE cycling; returns honest provider_gap."""
    res = capability_invoke(
        capability_id="network.device.poe_cycle.v1",
        parameters={
            "switch_ref": "gwn_switch_01",
            "port": 2,
            "provider": "grandstream_gwn",
            "dry_run": True,
        },
    )
    assert res["ok"] is False
    assert res["result"]["error"] == "provider_gap"
    assert "Grandstream GWN Cloud API does not support per-port PoE" in res["result"]["message"]
    assert "unifi" in res["result"]["supported_providers"]


def test_honest_provider_gap_for_unsupported_vendor():
    """Unsupported hardware vendor returns honest provider_gap, never fake success."""
    res = capability_invoke(
        capability_id="network.device.reboot.v1",
        parameters={
            "device_ref": "catalyst_3850",
            "provider": "cisco_ios",
            "dry_run": True,
        },
    )
    assert res["ok"] is False
    assert res["result"]["error"] == "provider_gap"
    assert "unifi" in res["result"]["supported_providers"]


def test_recovery_verification_capability():
    """Mock recovery is useful test evidence but is explicitly simulated."""
    res = capability_invoke(
        capability_id="network.device.verify_recovery.v1",
        parameters={
            "device_ref": "192.168.1.50",
            "provider": "unifi",
            "expected_status": "online",
            "mock_probe": True,
        },
    )
    assert res["ok"] is True
    assert res["status"] == "COMPLETED"
    assert res["result"]["recovered"] is True
    assert res["result"]["verification_mode"] == "SIMULATED"
    assert res["result"]["evidence_receipt"]["evidence_mode"] == "SIMULATED"
    assert res["result"]["current_status"] == "online"
    assert len(res["result"]["checks"]) >= 1


def test_recovery_without_real_probe_fails_closed():
    res = capability_invoke(
        capability_id="network.device.verify_recovery.v1",
        parameters={"device_ref": "ap_01", "provider": "unifi", "mock_probe": False},
    )
    assert res["ok"] is False
    assert res["result"]["error"] == "provider_probe_unavailable"
    assert res["result"]["verification_mode"] == "NOT_VERIFIED"
    assert res["result"]["recovered"] is False


def test_read_only_query_stays_unchanged(monkeypatch):
    """Verify network.device.query.v1 remains completely functional and read-only."""
    monkeypatch.setattr(
        "inneros_core_runtime.device_fabric.device_fabric_health",
        lambda site_id="": {"ok": True, "site": site_id, "healthy": True},
    )
    res = capability_invoke(
        capability_id="network.device.query.v1",
        parameters={"tenant_id": "lab", "site_id": "test_site", "sections": ["health"]},
    )
    assert res["ok"] is True
    assert res["status"] == "COMPLETED"
    assert res["result"]["mode"] == "read_only"


def test_idempotency_cache():
    """Idempotency key prevents duplicate execution and returns identical receipt."""
    idem_key = "idemp_test_key_abc_999"
    res1 = capability_invoke(
        capability_id="network.device.reboot.v1",
        parameters={"device_ref": "ap_office", "dry_run": True},
        idempotency_key=idem_key,
    )
    res2 = capability_invoke(
        capability_id="network.device.reboot.v1",
        parameters={"device_ref": "ap_office", "dry_run": True},
        idempotency_key=idem_key,
    )
    assert res1["execution_id"] == res2["execution_id"]
    assert res1["result"]["evidence_receipt"]["evidence_hash"] == res2["result"]["evidence_receipt"]["evidence_hash"]


def test_telemetry_sanitizer():
    """Customer identifiers, private IPs, and MACs are redacted before cloud transmission."""
    sensitive_data = {
        "site": "Torre Bellini Tower",
        "customer": "Rafael Lopez",
        "ap_ip": "192.168.3.15",
        "mac": "00:1A:2B:3C:4D:5E",
        "client_ip": "10.15.20.25",
        "api_token": "do-not-leak-this-token",
        "serial_number": "REAL-SERIAL-123",
        "latency_ms": 45,
    }
    sanitized, mapping = TelemetrySanitizer.sanitize(sensitive_data)
    san_str = json.dumps(sanitized)

    assert "Bellini" not in san_str
    assert "Rafael" not in san_str
    assert "192.168.3.15" not in san_str
    assert "00:1A:2B:3C:4D:5E" not in san_str
    assert "10.0.0.1" in san_str or "10.0.0.2" in san_str
    assert "do-not-leak-this-token" not in san_str
    assert "REAL-SERIAL-123" not in san_str
    assert len(mapping) >= 3


def test_nebius_nvidia_reasoning_mocked():
    """Nebius x NVIDIA reasoning engine returns structured diagnosis."""
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "root_cause": "Access Point buffer saturation",
                        "severity": "high",
                        "impact": "Wi-Fi packet loss",
                        "recommended_action": "reboot",
                        "recommended_capability": "network.device.reboot.v1",
                        "target_device_ref": "ap_01",
                        "target_port": None,
                        "requires_approval": True,
                        "confidence": 0.96,
                        "rationale": "Clear buffer queues and reboot radio firmware",
                        "verification_plan": {
                            "capability_id": "network.device.verify_recovery.v1",
                            "expected_status": "online",
                        },
                    })
                }
            }
        ]
    }

    reasoner = NebiusNvidiaReasoning(api_key="test_nebius_key", model="nvidia/test-nemotron")
    with mock.patch("urllib.request.urlopen") as mock_url:
        mock_cm = mock.MagicMock()
        mock_cm.read.return_value = json.dumps(mock_response).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_cm

        diag = reasoner.diagnose({"device_ref": "ap_main", "latency_ms": 250})
        assert diag["ok"] is True
        assert diag["provider"] == "nebius_token_factory"
        assert diag["inference_mode"] == "REAL"
        assert diag["provider_receipt"]["evidence_mode"] == "REAL"
        assert diag["diagnosis"]["recommended_action"] == "reboot"
        assert diag["diagnosis"]["recommended_capability"] == "network.device.reboot.v1"
        assert "deobfuscation_map" not in diag


def test_live_model_catalog_selects_only_nvidia_model():
    payload = {
        "data": [
            {"id": "meta/other-model"},
            {"id": "nvidia/Nemotron-Test-Open"},
        ]
    }
    reasoner = NebiusNvidiaReasoning(api_key="vault-materialized-for-test", model="")
    with mock.patch("urllib.request.urlopen") as mock_url:
        mock_cm = mock.MagicMock()
        mock_cm.read.return_value = json.dumps(payload).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_cm
        assert reasoner.resolve_live_nvidia_model() == "nvidia/Nemotron-Test-Open"


def test_nebius_fallback_to_local_reasoning():
    """When Nebius API key is missing or call fails, falls back smoothly to local reasoning."""
    reasoner = NebiusNvidiaReasoning(api_key="")  # No external key
    diag = reasoner.diagnose({"device_ref": "ap_down", "offline": True})

    assert diag["ok"] is True
    assert diag["provider"] == "local_heuristic"
    assert diag["inference_mode"] == "LOCAL_HEURISTIC"
    assert diag["fallback_engaged"] is True
    assert diag["diagnosis"]["recommended_action"] == "reboot"
    assert diag["diagnosis"]["requires_approval"] is True


def test_bounded_physical_ai_workflow_dry_run():
    """Execute complete 7-stage workflow in dry-run mode."""
    wf = run_physical_ai_workflow(
        device_ref="u7_ap_living",
        site_id="home_pcdoctor_lab",
        provider="unifi",
        dry_run=True,
    )
    assert wf["ok"] is True
    assert wf["status"] == "COMPLETED_DRY_RUN"
    assert wf["stages_executed"] == 7
    receipt = wf["evidence_receipt"]
    assert receipt["thesis"] == "Cloud intelligence. Local authority. Verified physical actions."
    assert receipt["authority"]["approved"] is False
    assert receipt["authority"]["dry_run"] is True
    assert receipt["verification"]["verification_mode"] == "SIMULATED"
    assert receipt["verification"]["real_recovery_verified"] is False
    assert receipt["verification"]["recovered"] is None
    assert receipt["verification"]["simulated_outcome"] is True


def test_bounded_physical_ai_workflow_blocked_without_approval():
    """Live workflow execution is blocked at policy stage without owner approval."""
    wf = run_physical_ai_workflow(
        device_ref="u7_ap_living",
        dry_run=False,
        owner_approved=False,
    )
    assert wf["ok"] is False
    assert wf["status"] == "BLOCKED_BY_POLICY"
    assert wf["error"] == "approval_required"
