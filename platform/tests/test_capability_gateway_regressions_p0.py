"""Regression tests for fail-closed capability outcomes and safe peer telemetry."""
from __future__ import annotations

from inneros_core_runtime import capability_gateway as gateway
from inneros_core_runtime import capability_gateway_peer as peer


def test_handler_explicit_failure_must_not_complete():
    capability_id = "test.p0.handler_failure.v1"
    gateway.register_capability(
        {"capability_id": capability_id, "mode": "read_only", "risk_class": "low"},
        lambda _params, _ctx: {"ok": False, "error": "helper_returncode_126"},
    )
    result = gateway.capability_invoke(capability_id, {})
    assert result["ok"] is False
    assert result["status"] == "FAILED"
    assert result["error"] == "helper_returncode_126"
    assert result["result"]["ok"] is False


def test_handler_success_remains_completed():
    capability_id = "test.p0.handler_success.v1"
    gateway.register_capability(
        {"capability_id": capability_id, "mode": "read_only", "risk_class": "low"},
        lambda _params, _ctx: {"ok": True, "healthy": True},
    )
    result = gateway.capability_invoke(capability_id, {})
    assert result["ok"] is True
    assert result["status"] == "COMPLETED"
    assert result["result"]["healthy"] is True


def test_peer_snapshot_redacts_process_argv_without_destroying_metrics():
    secret = "example-secret-must-never-leak"
    payload = {
        "ok": True,
        "node": "amd",
        "snapshot": {
            "hostname": {"stdout": "ralfiia-amd"},
            "memory": {"stdout": "healthy"},
            "processes": {
                "ok": True,
                "returncode": 0,
                "stdout": "python --api-key " + secret,
                "stderr": "potential sensitive output " + secret,
                "argv": ["python", "--api-key", secret],
            },
        },
    }
    result = peer._redact_observability_process_args(payload)
    assert result["snapshot"]["hostname"] == payload["snapshot"]["hostname"]
    assert result["snapshot"]["memory"] == payload["snapshot"]["memory"]
    assert result["snapshot"]["processes"] == {
        "redacted": True, "ok": True, "returncode": 0
    }
    assert secret not in repr(result)
    assert payload["snapshot"]["processes"]["argv"][-1] == secret


def test_peer_snapshot_preserves_failed_helper_status():
    result = peer._redact_observability_process_args(
        {"ok": False, "snapshot": {"helper_returncode": 126}}
    )
    assert result["ok"] is False
    assert result["error"] == "peer_observability_helper_failed"
    assert result["snapshot"]["helper_returncode"] == 126
