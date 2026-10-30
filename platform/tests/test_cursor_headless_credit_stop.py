"""No network/model calls: regress the repeated paid verification incident."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from inneros_core_runtime.cursor_headless_policy import headless_denial
from inneros_core_runtime import cursor_headless_dispatch as dispatch
from scripts import cursor_ops_headless_execute_one as worker


def active_task():
    return {"task_id": "ops_test", "status": "in_progress", "assignee": "cursor",
            "claim_token": "test-claim", "owner_authorized_at": "2026-10-29T00:00:00Z",
            "payload": {}, "execution_lane": "cursor_headless"}


@pytest.mark.parametrize("changes", [
    {"status": state} for state in ("verification", "failed", "completed", "cancelled", "superseded")
] + [
    {"superseded_by": "ops_replacement"}, {"do_not_auto_dispatch": True},
    {"payload": {"do_not_auto_dispatch": True}}, {"execution_stop": {"actor": "rafael"}},
    {"execution_lane": "cursor_interactive"}, {"payload": {"execution_lane": "cursor_interactive"}},
    {"execution_paused_for_deploy": True}, {"claim_token": ""},
    {"owner_authorized_at": None}, {"assignee": "codex"},
    {"headless_last_result": {"completion_submitted": True}},
    {"headless_last_result": {"completion_policy_blocked": True}},
    {"headless_dispatch_attempts": 3}, {"headless_dispatch_attempts": 400},
    {"headless_dispatch_attempts": "bad"},
])
def test_denied_task_cannot_spawn_even_with_force_retry(monkeypatch, changes):
    task = active_task() | deepcopy(changes)
    assert headless_denial(task)
    coll = Mock(); coll.find_one.return_value = task
    monkeypatch.setattr(dispatch.mongo_store, "get_db", lambda: {dispatch.OPS_TASKS_COL: coll})
    from inneros_core_runtime import cursor_headless_lanes as lanes
    monkeypatch.setattr(lanes, "is_ha_execution_node", lambda: True)
    monkeypatch.setattr(lanes, "hostname", lambda: "intel-test")
    monkeypatch.setattr(lanes, "available_slots", lambda: 4)
    monkeypatch.setenv("INNEROS_CURSOR_HEADLESS_EXECUTE", "1")
    for force in (False, True):
        assert not dispatch.spawn_headless_execute("ops_test", force_retry=force)["ok"]
    coll.update_one.assert_not_called()
    coll.find_one_and_update.assert_not_called()


def test_budget_counts_all_dispatches_not_only_dead_workers(monkeypatch):
    task = active_task(); task["headless_dispatch_attempts"] = 2
    assert not headless_denial(task)
    coll = Mock(); coll.find_one.return_value = task
    # Competing worker consumes the last slot between read and atomic reserve.
    coll.find_one_and_update.return_value = None
    monkeypatch.setattr(dispatch.mongo_store, "get_db", lambda: {dispatch.OPS_TASKS_COL: coll})
    from inneros_core_runtime import cursor_headless_lanes as lanes
    monkeypatch.setattr(lanes, "is_ha_execution_node", lambda: True)
    monkeypatch.setattr(lanes, "hostname", lambda: "intel-test")
    monkeypatch.setattr(lanes, "available_slots", lambda: 4)
    monkeypatch.setattr(lanes, "node_role", lambda: "intel")
    monkeypatch.setenv("INNEROS_CURSOR_HEADLESS_EXECUTE", "1")
    assert not dispatch.spawn_headless_execute("ops_test")["ok"]
    filt, update = coll.find_one_and_update.call_args.args
    assert {"headless_dispatch_attempts": {"$lt": 3, "$gte": 0}} in filt["$or"]
    assert update["$inc"]["headless_dispatch_attempts"] == 1
    assert filt["payload.do_not_auto_dispatch"] == {"$ne": True}
    task["headless_dispatch_attempts"] = 3
    assert headless_denial(task) == "headless_dispatch_budget_exhausted"


def test_worker_rejects_cancelled_task_before_sdk_or_lease(monkeypatch):
    task = active_task() | {"status": "cancelled"}
    coll = Mock(); coll.find_one.return_value = task
    monkeypatch.setattr(worker.mongo_store, "get_db", lambda: {worker.OPS_TASKS_COL: coll})
    sdk = Mock(); lease = Mock()
    monkeypatch.setattr(worker.che, "execute_claimed_task", sdk)
    monkeypatch.setattr(worker.cor, "renew_ops_lease", lease)
    monkeypatch.setattr("sys.argv", ["worker", "--task-id", "ops_test"])
    assert worker.main() == 2
    sdk.assert_not_called(); lease.assert_not_called(); coll.update_one.assert_not_called()


@pytest.mark.parametrize("status", ["claimed", "in_progress", "running"])
def test_valid_authorized_task_remains_eligible(status):
    assert headless_denial(active_task() | {"status": status}) == ""


def test_reserved_last_attempt_may_execute_but_not_reschedule():
    task = active_task() | {"headless_dispatch_attempts": 3}
    assert headless_denial(task)
    assert headless_denial(task, check_budget=False) == ""


def test_resume_selector_does_not_return_superseded_or_manual_tasks(monkeypatch):
    from scripts import cursor_ops_headless_autopilot as auto
    coll = Mock()
    coll.find.return_value.sort.return_value.limit.return_value = [
        active_task() | {"superseded_by": "ops_new"},
        active_task() | {"payload": {"do_not_auto_dispatch": True}},
        active_task() | {"status": "verification"},
    ]
    monkeypatch.setattr(auto.mongo_store, "get_db", lambda: {auto.OPS_TASKS_COL: coll})
    monkeypatch.setattr(auto.lanes, "hostname", lambda: "intel-test")
    assert auto._find_resume_on_host(4) == []
