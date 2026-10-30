from datetime import datetime, timezone, timedelta
from unittest.mock import Mock

from inneros_core_runtime.execution_resource_audit import findings


def test_audit_reports_stuck_and_superseded_executions():
    now = datetime.now(timezone.utc)
    tasks = [
        {"task_id": "stuck", "resource_guard": {"active_token": "test", "started_at": (now-timedelta(hours=1)).isoformat()}},
        {"task_id": "old", "superseded_by": "replacement"},
        {"task_id": "exhausted", "resource_guard": {"attempts": 3, "last_outcome": "failed"}},
        {"task_id": "success", "resource_guard": {"attempts": 3, "last_outcome": "success"}},
    ]
    assert {row["task_id"] for row in findings(tasks, now)} == {"stuck", "old", "exhausted"}


def test_audit_dedupes_notifications_and_bounds_delivery_retries(monkeypatch):
    from inneros_core_runtime import execution_resource_audit as audit
    from inneros_core_runtime import homeassistant_client as ha
    coll = Mock(); coll.find.return_value = [{"task_id": "old", "superseded_by": "new"}]
    state = {}
    monkeypatch.setattr(audit.mongo_store, "get_db", lambda: {"ralfia_ops_tasks": coll})
    monkeypatch.setattr(audit.mongo_store, "get_coordination_state", lambda key: {"state": state.copy()})
    monkeypatch.setattr(audit.mongo_store, "upsert_coordination_state", lambda **kw: state.update(kw["data"]))
    send = Mock(return_value={"ok": False})
    monkeypatch.setattr(ha, "call_service", send)
    for _ in range(10):
        audit.run(notify=True)
    assert send.call_count == 3


def test_audit_detects_guard_overwrite_or_missing_decorator(tmp_path):
    from inneros_core_runtime import execution_resource_audit as audit
    for filename, name, decorator in audit.HOOKS:
        (tmp_path / filename).write_text(f"@{decorator}\ndef {name}(): pass\n")
    assert not audit.source_findings(tmp_path)
    (tmp_path / "local_model_router.py").write_text("def run_local_model(): pass\n")
    notices = audit.source_findings(tmp_path)
    assert len(notices) == 1
    assert notices[0]["reason"] == "resource_guard_hook_missing"


def test_missing_hook_latches_circuit_and_stops_only_known_launchers(monkeypatch):
    from inneros_core_runtime import execution_resource_audit as audit
    coll = Mock(); coll.find.return_value = []
    monkeypatch.setattr(audit.mongo_store, "get_db", lambda: {"ralfia_ops_tasks": coll})
    monkeypatch.setattr(audit.mongo_store, "get_coordination_state", lambda key: {})
    record = Mock(); stop = Mock()
    monkeypatch.setattr(audit.mongo_store, "upsert_coordination_state", record)
    monkeypatch.setattr(audit.subprocess, "run", stop)
    monkeypatch.setattr(audit, "source_findings", lambda: [{"task_id": "runtime:test", "reason": "resource_guard_hook_missing"}])
    audit.run()
    assert record.call_args_list[0].kwargs["data"]["block_new_work"] is True
    assert "ralfia-external-repair-agent.service" in stop.call_args.args[0]
