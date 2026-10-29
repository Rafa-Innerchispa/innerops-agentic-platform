"""Requirements amendments: ACK ≠ applied; idempotency; completion barrier."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime import coordination_ingest as ci
from inneros_core_runtime import ops_task_requirements as otr


def _task_doc(**overrides):
    base = {
        "task_id": "ops_req_demo",
        "status": "in_progress",
        "assignee": "cursor",
        "requirements_version": 2,
        "revision": 2,
        "objective": "baseline",
        "payload": {},
    }
    base.update(overrides)
    return base


def test_register_amendment_idempotent():
    db = MagicMock()
    tasks = MagicMock()
    events = MagicMock()
    db.__getitem__.side_effect = lambda name: tasks if name == otr.OPS_TASKS_COL else events
    tasks.find_one.return_value = _task_doc()
    events.find_one.return_value = None

    with patch.object(otr.mongo_store, "get_db", return_value=db):
        first = otr.register_amendment(
            "ops_req_demo",
            message_id="msg_a",
            idempotency_key="idem-1",
            delta={"append_objective": "extra scope"},
            auto_accept=False,
        )
        assert first["ok"] and first["lifecycle"] == "pending"
        events.insert_one.assert_called_once()
        events.find_one.return_value = {"event_id": first["event_id"], "lifecycle": "pending"}
        second = otr.register_amendment(
            "ops_req_demo",
            message_id="msg_a",
            idempotency_key="idem-1",
            delta={"append_objective": "extra scope"},
        )
        assert second.get("duplicate") is True


def test_completion_blocked_while_amendment_pending():
    with patch.object(otr, "pending_amendments", return_value=[{"event_id": "req_x", "lifecycle": "accepted"}]):
        block = otr.completion_blocked_by_amendments("ops_req_demo")
    assert block["blocked"] is True


def test_apply_amendment_cas_bumps_version():
    db = MagicMock()
    tasks = MagicMock()
    events = MagicMock()
    db.__getitem__.side_effect = lambda name: tasks if name == otr.OPS_TASKS_COL else events
    events.find_one.return_value = {
        "event_id": "req_apply",
        "task_id": "ops_req_demo",
        "lifecycle": "accepted",
        "delta": {"append_objective": " delta"},
        "requirements_version_at_register": 2,
    }
    tasks.find_one.return_value = _task_doc()
    tasks.find_one_and_update.return_value = _task_doc(requirements_version=3)

    with patch.object(otr.mongo_store, "get_db", return_value=db):
        out = otr.apply_amendment("req_apply")
    assert out["ok"] is True
    assert out["requirements_version"] == 3


def test_reply_without_p_header_becomes_amendment_not_new_task():
    with patch("raphiia_openai.memory.agent_messages") as am:
        am.create_agent_message.return_value = {
            "ok": True,
            "message_id": "msg_reply",
            "correlation_id": "corr-1",
        }
        with patch("inneros_core_runtime.ops_task_requirements.ingest_message_as_amendment") as ingest:
            ingest.return_value = {"ok": True, "lifecycle": "pending", "event_id": "req_1"}
            out = ci.ingest_agent_message(
                from_agent="chatgpt",
                target_agent="cursor",
                title="Pequeño ajuste",
                body="Añade prueba de idempotencia",
                reply_to="msg_parent",
                payload={"task_id": "ops_parent"},
            )
    assert out.get("requirements_amendment", {}).get("ok") is True
    assert out.get("task_work_done") is False


def test_inbox_consumer_ack_semantics():
    from scripts import cursor_ops_inbox_consumer as consumer

    with patch.object(consumer.am, "poll_agent_inbox", return_value={"messages": [], "count": 0, "acknowledged": ["m1"]}):
        with patch.object(consumer.cep, "register_cursor_consumer_heartbeat", return_value={"ok": True}):
            with patch.object(consumer.cep, "read_inbox_consumer_liveness", return_value={"active": True}):
                with patch.object(consumer.cep, "read_session_liveness", return_value={"active": False}):
                    with patch.object(consumer.cep, "classify_cursor_execution", return_value={}):
                        out = consumer.run(limit=5)
    sem = out["delivery_semantics"]
    assert sem["message_read_ack"] is True
    assert sem["task_work_done"] is False
    assert sem["requirements_applied"] is False
