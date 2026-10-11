"""AG-41 observability must fail closed and not disclose process argv."""
from __future__ import annotations

from inneros_core_runtime.agents import ag41_peer_ops_executor as ag41


def test_observability_redacts_process_command_credentials(monkeypatch):
    sentinel = "DO_NOT_EXPOSE_FAKE_SECRET"
    monkeypatch.setattr(ag41.whatsapp_service_ops, "normalize_node", lambda n: "primary")
    monkeypatch.setattr(ag41, "_helper", lambda *_a, **_kw: {
        "ok": True, "helper_returncode": 0,
        "hostname": {"stdout": "intel"},
        "processes": {
            "ok": True, "returncode": 0,
            "stdout": "cursor-agent --api-key " + sentinel,
            "stderr": sentinel, "argv": ["--api-key", sentinel],
        },
        "raw": {"stdout": sentinel},
    })
    result = ag41.peer_observability_snapshot("intel")
    assert result["ok"] is True
    assert result["snapshot"]["hostname"]["stdout"] == "intel"
    assert result["snapshot"]["processes"] == {
        "redacted": True, "ok": True, "returncode": 0
    }
    assert sentinel not in repr(result)


def test_observability_rejects_helper_returncode_126(monkeypatch):
    monkeypatch.setattr(ag41.whatsapp_service_ops, "normalize_node", lambda n: "primary")
    monkeypatch.setattr(ag41, "_helper", lambda *_a, **_kw: {
        "ok": False, "helper_returncode": 126, "raw": {"stderr": "denied"}
    })
    result = ag41.peer_observability_snapshot("intel")
    assert result["ok"] is False
    assert result["error"] == "peer_helper_command_denied"
    assert result["snapshot"]["helper_returncode"] == 126
    assert "raw" not in result["snapshot"]
