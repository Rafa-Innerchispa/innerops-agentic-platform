"""Offline FMEA matrix for 12 coordination invariants (issue #8 scoped, no side effects)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime import ops_auto_claim_admission as oaca
from inneros_core_runtime import ops_owner_approval_ha as oah
from inneros_core_runtime import ops_task_requirements as otr
from scripts import cursor_ops_inbox_consumer as inbox


FMEA_MATRIX = [
    ("INV-01", "inbox_ack_not_task_done", lambda: _ack_not_done()),
    ("INV-02", "no_claim_without_owner_grant", lambda: _no_forge_grant()),
    ("INV-03", "completion_blocked_pending_amendments", lambda: _completion_barrier()),
    ("INV-04", "requirements_cas_version", lambda: _cas_stale()),
    ("INV-05", "amendment_idempotent_register", lambda: _idempotent_register()),
    ("INV-06", "single_continuation_terminal_parent", lambda: _single_continuation()),
    ("INV-07", "synthetic_not_real_class", lambda: _synthetic_class()),
    ("INV-08", "peer_ops_owner_gate", lambda: _peer_ops_gate()),
    ("INV-09", "paid_model_requires_grant", lambda: _paid_grant()),
    ("INV-10", "unknown_budget_not_zero", lambda: _unknown_budget()),
    ("INV-11", "double_claim_foreign_provider", lambda: _foreign_claim()),
    ("INV-12", "replay_checkpoint_idempotent", lambda: _checkpoint_replay()),
]


def _ack_not_done():
    with patch.object(inbox.am, "poll_agent_inbox", return_value={"messages": [], "count": 0, "acknowledged": ["m"]}):
        with patch.object(inbox.cep, "register_cursor_consumer_heartbeat", return_value={"ok": True}):
            with patch.object(inbox.cep, "read_inbox_consumer_liveness", return_value={"active": True}):
                with patch.object(inbox.cep, "read_session_liveness", return_value={"active": False}):
                    with patch.object(inbox.cep, "classify_cursor_execution", return_value={}):
                        out = inbox.run(limit=1)
    sem = out["delivery_semantics"]
    return sem["message_read_ack"] and not sem["task_work_done"]


def _no_forge_grant():
    row = {"task_id": "x", "status": "awaiting_cursor_claim", "assignee": "cursor", "payload": {"owner_approved": True}}
    return oaca.claim_admission(row, provider="cursor", ready=True)["reason"] == "owner_authorization_not_recorded"


def _completion_barrier():
    with patch.object(otr, "pending_amendments", return_value=[{"lifecycle": "pending"}]):
        return otr.completion_blocked_by_amendments("t")["blocked"]


def _cas_stale():
    db = MagicMock()
    tasks = MagicMock()
    events = MagicMock()
    db.__getitem__.side_effect = lambda n: tasks if n == otr.OPS_TASKS_COL else events
    events.find_one.return_value = {
        "event_id": "e",
        "task_id": "t",
        "lifecycle": "accepted",
        "delta": {},
        "requirements_version_at_register": 1,
    }
    tasks.find_one.return_value = {"task_id": "t", "requirements_version": 3, "status": "in_progress"}
    with patch.object(otr.mongo_store, "get_db", return_value=db):
        return otr.apply_amendment("e")["error"] == "stale_amendment_base_version"


def _idempotent_register():
    db = MagicMock()
    tasks = MagicMock()
    events = MagicMock()
    db.__getitem__.side_effect = lambda n: tasks if n == otr.OPS_TASKS_COL else events
    tasks.find_one.return_value = {"task_id": "t", "requirements_version": 0}
    events.find_one.return_value = {"event_id": "req_dup", "lifecycle": "pending"}
    with patch.object(otr.mongo_store, "get_db", return_value=db):
        return otr.register_amendment("t", message_id="m", idempotency_key="k", delta={}).get("duplicate") is True


def _single_continuation():
    db = MagicMock()
    db.__getitem__.return_value.find_one.side_effect = [None, {"task_id": "child"}]
    with patch.object(otr.mongo_store, "get_db", return_value=db):
        with patch("inneros_core_runtime.coordination_live.create_ops_task", return_value={"ok": True, "task_id": "child"}) as create:
            otr.create_continuation_for_amendment({"event_id": "e", "delta": {}}, parent={"task_id": "p", "status": "completed"})
            otr.create_continuation_for_amendment({"event_id": "e", "delta": {}}, parent={"task_id": "p", "status": "completed"})
    return create.call_count == 1


def _synthetic_class():
    from inneros_core_runtime import interactive_provider_bounded_executor as ipbe

    return ipbe.EXECUTION_SYNTHETIC_CANARY != ipbe.EXECUTION_PROVIDER_REAL


def _peer_ops_gate():
    env = {
        "task_kind": "peer_ops",
        "execution_lane": "peer_ops",
        "peer_action": "status",
        "requested_agent": "AG-41",
        "owner_approved": False,
        "service_id": "ag-41",
    }
    binding = eb.resolve_execution_binding(env)
    return binding.get("error") == "peer_ops_owner_approval_required"


def _paid_grant():
    db = MagicMock()
    tasks = MagicMock()
    grants = MagicMock()
    db.__getitem__.side_effect = lambda n: tasks if n == oah.OPS_TASKS_COL else grants
    tasks.find_one.return_value = {"task_id": "t", "assignee": "codex", "owner_authorized_at": "x"}
    grants.find_one.return_value = None
    with patch.object(oah.mongo_store, "get_db", return_value=db):
        return oah.paid_execution_allowed("t")["error"] == "owner_budget_grant_required"


def _unknown_budget():
    return oah.parse_natural_language_budget("")["usd_hard_limit"] is None


def _foreign_claim():
    row = {"task_id": "x", "status": "awaiting_cursor_claim", "assignee": "cursor", "owner_authorized_at": "z"}
    return oaca.claim_admission(row, provider="codex", ready=True)["reason"] == "different_assignee"


def _checkpoint_replay():
    """Empty checkpoint queues must be safe to replay (crash/reboot worker)."""
    with patch.object(otr, "checkpoint_pending_revision", return_value={"count": 0, "pending_events": []}):
        with patch.object(otr.mongo_store, "get_db") as gdb:
            db = MagicMock()
            tasks = MagicMock()
            ev = MagicMock()
            db.__getitem__.side_effect = lambda n: tasks if n == otr.OPS_TASKS_COL else ev
            tasks.find_one.return_value = {"task_id": "t", "requirements_version": 1}
            ev.find.return_value.sort.return_value = []
            first = otr.process_checkpoint_amendments("t")
            second = otr.process_checkpoint_amendments("t")
    return first.get("ok") and second.get("ok")


def test_fmea_invariants_matrix():
    results = {code: fn() for code, _name, fn in FMEA_MATRIX}
    failures = [code for code, ok in results.items() if not ok]
    assert not failures, f"FMEA failures: {failures}"
