"""Regression: AG-41 A2A must execute the typed read-only request, not a snapshot."""
from __future__ import annotations

import json

from inneros_core_runtime.agents import pool_agent_runners as pool


def _request(action="status", service_id="mcp", node="amd"):
    return json.dumps({
        "protocol": "peer_ops.v1",
        "action": action,
        "service_id": service_id,
        "node": node,
    })


def test_ag41_plain_language_is_not_success():
    result = pool.run_ag41("restart my server", dry_run=False)
    assert result["ok"] is False
    assert result["error"] == "peer_ops_structured_request_required"


def test_ag41_unaccredited_mutation_is_denied_even_with_owner_claim():
    payload = json.loads(_request("restart"))
    payload["owner_approved"] = True
    result = pool.run_ag41(json.dumps(payload), dry_run=False)
    assert result["ok"] is False
    assert result["error"] == "peer_ops_mutation_requires_governed_approval"


def test_ag41_real_status_calls_service_provider(monkeypatch):
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41
    calls = []
    monkeypatch.setattr(ag41, "ALLOWLIST_SERVICES", ("mcp",))
    monkeypatch.setattr(ag41, "peer_ops_status", lambda service_id, node: (
        calls.append((service_id, node)) or {
            "ok": True, "healthy": True, "health": "up",
            "system_state": "active", "telemetry": "systemd",
        }
    ))
    result = pool.run_ag41(_request(), dry_run=False)
    assert result["ok"] is True
    assert result["protocol"] == "peer_ops.v1"
    assert result["action"] == "status"
    assert result["verified"] is True
    assert result["read_only"] is True
    assert calls == [("mcp", "amd")]


def test_ag41_remote_unavailable_cannot_fake_verified_status(monkeypatch):
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41
    monkeypatch.setattr(ag41, "ALLOWLIST_SERVICES", ("mcp",))
    monkeypatch.setattr(ag41, "peer_ops_status", lambda service_id, node: {
        "ok": True, "healthy": True, "health": "up",
        "system_state": "unknown", "telemetry": "remote_unavailable",
    })
    result = pool.run_ag41(_request(), dry_run=False)
    assert result["ok"] is False
    assert result["error"] == "peer_ops_live_status_evidence_missing"


def test_ag41_dry_run_cannot_claim_live_status(monkeypatch):
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41
    monkeypatch.setattr(ag41, "ALLOWLIST_SERVICES", ("mcp",))
    result = pool.run_ag41(_request(), dry_run=True)
    assert result["ok"] is False
    assert result["dry_run"] is True


def test_ag41_unknown_service_is_blocked(monkeypatch):
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41
    monkeypatch.setattr(ag41, "ALLOWLIST_SERVICES", ("mcp",))
    result = pool.run_ag41(_request(service_id="nonexistent"), dry_run=False)
    assert result["ok"] is False
    assert result["error"] == "peer_ops_service_not_allowlisted"
