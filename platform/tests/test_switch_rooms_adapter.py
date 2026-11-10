import pytest
from unittest.mock import patch
from inneros_core_runtime.switch_rooms_adapter import SwitchRoomsAdapter, _dedup_cache


@pytest.fixture
def adapter():
    return SwitchRoomsAdapter(switch_url="http://127.0.0.1:62326", room_name="test-room", node_id="AMD-1.5")


def test_ping_command_returns_correlated_pong(adapter):
    res = adapter.handle_command("!ping", correlation_id="CID-TEST-12345")
    assert res["ok"] is True
    assert res["command"] == "!ping"
    assert res["correlation_id"] == "CID-TEST-12345"
    assert "PONG" in res["response_text"]
    assert "AMD-1.5" in res["response_text"]
    assert res["latency_ms"] >= 0


def test_custom_cid_in_text(adapter):
    res = adapter.handle_command("!ping CID-AUTO-999")
    assert res["ok"] is True
    assert res["correlation_id"] == "CID-AUTO-999"
    assert "CID-AUTO-999" in res["response_text"]


def test_status_command_returns_runtime_state(adapter):
    with patch.object(adapter, "check_switch_health") as mock_health:
        mock_health.return_value = {"ok": True, "status": "ok", "latency_ms": 1.2}
        res = adapter.handle_command("!status", correlation_id="CID-STATUS-1")
        assert res["ok"] is True
        assert res["command"] == "!status"
        assert res["correlation_id"] == "CID-STATUS-1"
        assert "Switch Gateway: ONLINE" in res["response_text"]
        assert "Physical Safety Gate: ACTIVE" in res["response_text"]


def test_incident_command_read_only_triage(adapter):
    res = adapter.handle_command("!incident", correlation_id="CID-INC-1")
    assert res["ok"] is True
    assert res["command"] == "!incident"
    assert res["correlation_id"] == "CID-INC-1"
    assert "Active Incidents:" in res["response_text"]
    assert "Safety Policy: READ_ONLY_TRIAGE" in res["response_text"]


def test_mutating_command_rejected_by_policy(adapter):
    for bad_cmd in ("!reboot", "!deploy", "!delete", "!create"):
        res = adapter.handle_command(bad_cmd, correlation_id=f"CID-BAD-{bad_cmd}")
        assert res["ok"] is False
        assert res["error"] == "mutating_command_rejected_by_policy"
        assert "FAIL" in res["response_text"]
        assert "rejected" in res["response_text"]


def test_deduplication_cache(adapter):
    _dedup_cache.clear()
    msg_id = "msg-unique-uuid-1"
    res1 = adapter.handle_command("!ping", message_id=msg_id)
    assert res1["ok"] is True

    res2 = adapter.handle_command("!ping", message_id=msg_id)
    assert res2["ok"] is False
    assert res2["error"] == "duplicate_message_ignored"
