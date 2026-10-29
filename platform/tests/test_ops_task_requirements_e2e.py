"""E2E-style amendment lifecycle: checkpoint apply, double addendum, stale worker, terminal continuation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime import ops_task_requirements as otr


def _task(**overrides):
    base = {
        "task_id": "ops_e2e_amend",
        "status": "in_progress",
        "assignee": "cursor",
        "requirements_version": 1,
        "revision": 1,
        "objective": "base",
        "payload": {},
    }
    base.update(overrides)
    return base


def _mock_db(task: dict, events: list[dict]):
    db = MagicMock()
    tasks = MagicMock()
    evcol = MagicMock()

    def getitem(name):
        if name == otr.OPS_TASKS_COL:
            return tasks
        if name == otr.COL_EVENTS:
            return evcol
        raise KeyError(name)

    db.__getitem__.side_effect = getitem
    def task_find_one(query, projection=None):
        return task

    tasks.find_one.side_effect = task_find_one

    def task_update(query, update, **kwargs):
        nonlocal task
        if query.get("requirements_version") == task.get("requirements_version"):
            task = {**task, **update.get("$set", {}), "requirements_version": task["requirements_version"] + 1}
            return task
        return None

    tasks.find_one_and_update.side_effect = task_update

    def ev_find(query, projection=None):
        m = MagicMock()
        lifecycle = query.get("lifecycle")
        tid = query.get("task_id")
        rows = [e for e in events if e.get("task_id") == tid]
        if isinstance(lifecycle, dict) and "$in" in lifecycle:
            rows = [e for e in rows if e.get("lifecycle") in lifecycle["$in"]]
        elif lifecycle:
            rows = [e for e in rows if e.get("lifecycle") == lifecycle]
        m.sort.return_value = rows
        return m

    evcol.find.side_effect = ev_find

    def ev_update(query, update, **kwargs):
        for e in events:
            if e.get("event_id") == query.get("event_id") and e.get("lifecycle") == query.get("lifecycle"):
                e.update(update.get("$set", {}))
                return MagicMock(modified_count=1)

    def ev_find_one(query, projection=None):
        for e in events:
            if query.get("event_id") and e.get("event_id") != query.get("event_id"):
                continue
            if "lifecycle" in query and e.get("lifecycle") != query.get("lifecycle"):
                continue
            return e
        return None

    evcol.find_one.side_effect = ev_find_one
    evcol.find_one_and_update.side_effect = lambda q, u, **kw: next(
        (e for e in events if e.get("event_id") == q.get("event_id") and e.get("lifecycle") == q.get("lifecycle")),
        None,
    )
    evcol.update_one.side_effect = ev_update
    return db, tasks, events


def test_process_checkpoint_applies_accepted_chain():
    events = [
        {
            "event_id": "req_a",
            "task_id": "ops_e2e_amend",
            "lifecycle": "accepted",
            "delta": {"append_objective": " a"},
            "requirements_version_at_register": 1,
        }
    ]
    db, tasks, events_ref = _mock_db(_task(), events)
    with patch.object(otr.mongo_store, "get_db", return_value=db):
        out = otr.process_checkpoint_amendments("ops_e2e_amend", actor="cursor")
    assert out["ok"] is True
    assert any(p.get("step") == "apply_verify" for p in out["processed"])


def test_double_addendum_idempotent_register():
    db = MagicMock()
    tasks = MagicMock()
    evcol = MagicMock()
    db.__getitem__.side_effect = lambda n: tasks if n == otr.OPS_TASKS_COL else evcol
    tasks.find_one.return_value = _task()
    evcol.find_one.side_effect = [None, {"event_id": "req_x", "lifecycle": "pending"}]
    with patch.object(otr.mongo_store, "get_db", return_value=db):
        first = otr.register_amendment("ops_e2e_amend", message_id="m1", idempotency_key="idem-x", delta={})
        second = otr.register_amendment("ops_e2e_amend", message_id="m1", idempotency_key="idem-x", delta={})
    assert first["ok"] and second.get("duplicate") is True
    assert evcol.insert_one.call_count == 1


def test_stale_worker_apply_rejected():
    ev = {
        "event_id": "req_stale",
        "task_id": "ops_e2e_amend",
        "lifecycle": "accepted",
        "delta": {"append_objective": " stale"},
        "requirements_version_at_register": 0,
    }
    db = MagicMock()
    tasks = MagicMock()
    evcol = MagicMock()
    db.__getitem__.side_effect = lambda n: tasks if n == otr.OPS_TASKS_COL else evcol
    evcol.find_one.return_value = ev
    tasks.find_one.return_value = _task(requirements_version=2)
    tasks.find_one_and_update.return_value = None
    with patch.object(otr.mongo_store, "get_db", return_value=db):
        out = otr.apply_amendment("req_stale")
    assert out["ok"] is False
    assert out["error"] == "stale_amendment_base_version"


def test_terminal_parent_creates_single_continuation():
    parent = _task(status="completed")
    event = {"event_id": "req_term", "task_id": "ops_e2e_amend", "delta": {"append_objective": "more"}}
    db = MagicMock()
    tasks = MagicMock()
    db.__getitem__.return_value = tasks
    tasks.find_one.side_effect = [None, {"task_id": "ops_child"}]
    with patch.object(otr.mongo_store, "get_db", return_value=db):
        with patch("inneros_core_runtime.coordination_live.create_ops_task", return_value={"ok": True, "task_id": "ops_child"}) as create:
            first = otr.create_continuation_for_amendment(event, parent=parent)
            second = otr.create_continuation_for_amendment(event, parent=parent)
    assert first.get("task_id") == "ops_child"
    assert second.get("duplicate") is True
    create.assert_called_once()
