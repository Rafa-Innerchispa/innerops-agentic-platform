from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime.productivity_metrics import record_task_completion

PIN = "gemini-3.7-flash-medium"


def _mock_db():
    col = MagicMock()
    db = MagicMock()
    db.__getitem__.return_value = col
    return db, col


def test_record_completion_builds_measured_event() -> None:
    db, col = _mock_db()
    col.find_one.return_value = None
    task = {
        "task_id": "ops_m1",
        "execution_lane": "antigravity_interactive",
        "preferred_provider": "antigravity",
        "created_at": "2026-11-12T05:00:00+00:00",
        "claimed_at": "2026-11-12T06:00:00+00:00",
    }
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = record_task_completion(task, outcome="verification", requested="completed",
                                     now_iso="2026-11-12T07:00:00+00:00")

    assert out["ok"] is True
    assert out["created"] is True
    doc = col.update_one.call_args.args[1]["$set"]
    assert col.update_one.call_args.args[0] == {"task_key": "ops_m1"}
    assert doc["measurement_class"] == "measured"
    assert doc["verified"] is True
    assert doc["human_baseline_minutes"] == 0.0
    assert doc["assisted_minutes"] == 60.0
    assert doc["saved_minutes"] == 0.0
    assert "antigravity_interactive" in doc["notes"]
    assert "outcome=verification" in doc["notes"]
    assert "requested=completed" in doc["notes"]
    assert doc["evidence_refs"] == ["ops_m1"]


def test_record_completion_bad_timestamps_zero_duration() -> None:
    db, col = _mock_db()
    col.find_one.return_value = None
    task = {"task_id": "ops_m2", "created_at": "not-a-date", "claimed_at": None}
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = record_task_completion(task, outcome="failed", now_iso="also-bad")

    assert out["ok"] is True
    doc = col.update_one.call_args.args[1]["$set"]
    assert doc["assisted_minutes"] == 0.0


def test_record_completion_requires_task_id() -> None:
    db, col = _mock_db()
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = record_task_completion({}, outcome="verification")

    assert out["ok"] is False
    assert out["error"] == "task_key_required"
    col.update_one.assert_not_called()


def test_recovery_records_self_heal_incident() -> None:
    from inneros_core_runtime.ops_interactive_recovery import recover_expired_lease_interactive_ops_tasks

    db, col = _mock_db()
    col.find.return_value.sort.return_value.limit.return_value = [{
        "task_id": "ops_exp1",
        "status": "claimed",
        "assignee": "antigravity",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claimed_by": "antigravity",
        "claim_token": "tok1",
        "lease_until": "2026-01-01T00:00:00+00:00",
    }]
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.self_heal_metrics.record_self_heal_incident",
              return_value={"ok": True}) as rec,
    ):
        out = recover_expired_lease_interactive_ops_tasks()

    assert out["ok"] is True
    assert len(out["recovered"]) == 1
    payload = rec.call_args.args[0]
    assert payload["service_id"] == "ops-coordination-leases"
    assert payload["repair_action"] == "recover_expired_lease_interactive_ops_tasks"
    assert payload["repair_action_ok"] is True
    assert payload["verified_recovered"] is True
    assert payload["automatic"] is True
    assert payload["evidence_refs"] == ["ops_exp1"]
    assert payload["repair_duration_seconds"] >= 0.0


def test_recovery_survives_recording_failure() -> None:
    from inneros_core_runtime.ops_interactive_recovery import recover_expired_lease_interactive_ops_tasks

    db, col = _mock_db()
    col.find.return_value.sort.return_value.limit.return_value = [{
        "task_id": "ops_exp1",
        "status": "claimed",
        "assignee": "antigravity",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claimed_by": "antigravity",
        "claim_token": "tok1",
        "lease_until": "2026-01-01T00:00:00+00:00",
    }]
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.self_heal_metrics.record_self_heal_incident",
              side_effect=RuntimeError("mongo down")),
    ):
        out = recover_expired_lease_interactive_ops_tasks()

    assert out["ok"] is True
    assert len(out["recovered"]) == 1


def test_interactive_complete_records_completion() -> None:
    from inneros_core_runtime import interactive_ops_runner as ior

    task = {
        "task_id": "ops_c1",
        "status": "claimed",
        "assignee": "antigravity",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "task_class": "verification",
        "claim_token": "tok_c",
        "lease_until": "2030-01-01T00:00:00+00:00",
        "created_at": "2026-11-12T05:00:00+00:00",
        "claimed_at": "2026-11-12T06:00:00+00:00",
    }
    db, col = _mock_db()
    col.find_one.return_value = task
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.interactive_ops_runner.pinned_model", return_value=PIN),
        patch("inneros_core_runtime.ops_task_requirements.completion_blocked_by_amendments",
              return_value={"blocked": False}),
        patch("inneros_core_runtime.ops_lifecycle.submit_completion_with_temporal_fallback",
              return_value={"ok": True, "temporal": {"ok": True}}),
        patch("inneros_core_runtime.ops_execution_state.refresh_current_execution_state"),
        patch("inneros_core_runtime.productivity_metrics.record_task_completion",
              return_value={"ok": True}) as rec,
    ):
        out = ior.complete_ops_task("antigravity", "ops_c1", claim_token="tok_c",
                                    status="completed", evidence={"notes": "probe ok"})

    assert out["ok"] is True
    rec.assert_called_once()
    assert rec.call_args.args[0]["task_id"] == "ops_c1"
    assert rec.call_args.kwargs["outcome"] == "verification"
    assert rec.call_args.kwargs["requested"] == "completed"


def test_cursor_complete_records_completion() -> None:
    from inneros_core_runtime import cursor_ops_runner as cor

    task = {
        "task_id": "ops_c2",
        "status": "in_progress",
        "assignee": "cursor",
        "claim_token": "tok_d",
        "lease_until": "2030-01-01T00:00:00+00:00",
        "created_at": "2026-11-12T05:00:00+00:00",
    }
    db, col = _mock_db()
    col.find_one.return_value = task
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.ops_task_requirements.completion_blocked_by_amendments",
              return_value={"blocked": False}),
        patch("inneros_core_runtime.ops_deploy_execution_pause.completion_requires_deploy_pause",
              return_value=False),
        patch("inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
              return_value={"ok": True}),
        patch("inneros_core_runtime.cursor_ops_runner._publish_task_event"),
        patch("inneros_core_runtime.cursor_ops_runner.heartbeat_ops_task"),
        patch("inneros_core_runtime.productivity_metrics.record_task_completion",
              return_value={"ok": True}) as rec,
    ):
        out = cor.complete_ops_task("ops_c2", claim_token="tok_d",
                                    status="completed", evidence={"commit_sha": "abc123def"})

    assert out["ok"] is True
    assert out["status"] == "verification"
    rec.assert_called_once()
    assert rec.call_args.kwargs["outcome"] == "verification"


def test_cursor_failed_completion_records_failed_outcome() -> None:
    from inneros_core_runtime import cursor_ops_runner as cor

    task = {
        "task_id": "ops_c3",
        "status": "in_progress",
        "assignee": "cursor",
        "claim_token": "tok_e",
        "lease_until": "2030-01-01T00:00:00+00:00",
    }
    db, col = _mock_db()
    col.find_one.return_value = task
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.ops_task_requirements.completion_blocked_by_amendments",
              return_value={"blocked": False}),
        patch("inneros_core_runtime.ops_deploy_execution_pause.classify_terminal_pause_status",
              return_value="failed"),
        patch("inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
              return_value={"ok": True}),
        patch("inneros_core_runtime.cursor_ops_runner._publish_task_event"),
        patch("inneros_core_runtime.productivity_metrics.record_task_completion",
              return_value={"ok": True}) as rec,
    ):
        out = cor.complete_ops_task("ops_c3", claim_token="tok_e", status="failed", evidence={})

    assert out["ok"] is True
    assert out["status"] == "failed"
    rec.assert_called_once()
    assert rec.call_args.kwargs["outcome"] == "failed"


def test_workflow_mirror_completed_records_completion() -> None:
    import asyncio

    from inneros_core_runtime import temporal_activities as ta

    envelope = {
        "task_id": "ops_w1",
        "execution_lane": "local_dev_swarm",
        "preferred_provider": "dev_swarm",
        "assignee": "dev_swarm",
        "created_at": "2026-11-12T05:00:00+00:00",
    }
    evidence = {"completed_at": "2026-11-12T06:00:00+00:00", "agent_result": {"ok": True}}
    client = MagicMock()
    db = MagicMock()
    col = MagicMock()
    client.__getitem__.return_value = db
    db.__getitem__.return_value = col
    col.find_one.return_value = {"status": "running", "revision": 1}
    with (
        patch.object(ta, "_mongo_projection_client", return_value=(client, "testdb")),
        patch.object(ta, "_safe_heartbeat"),
        patch("inneros_core_runtime.ops_lifecycle.emit_owner_terminal_whatsapp"),
        patch("inneros_core_runtime.productivity_metrics.record_task_completion",
              return_value={"ok": True}) as rec,
    ):
        out = asyncio.run(ta.activity_sync_mongo_mirror(envelope, "completed", evidence))

    assert out["ok"] is True
    rec.assert_called_once()
    assert rec.call_args.args[0]["task_id"] == "ops_w1"
    assert rec.call_args.kwargs["outcome"] == "completed"
    assert rec.call_args.kwargs["source"] == "workflow_complete"


def test_workflow_mirror_failed_does_not_record() -> None:
    import asyncio

    from inneros_core_runtime import temporal_activities as ta

    envelope = {"task_id": "ops_w2", "execution_lane": "local_dev_swarm"}
    client = MagicMock()
    db = MagicMock()
    col = MagicMock()
    client.__getitem__.return_value = db
    db.__getitem__.return_value = col
    col.find_one.return_value = {"status": "running", "revision": 1}
    with (
        patch.object(ta, "_mongo_projection_client", return_value=(client, "testdb")),
        patch.object(ta, "_safe_heartbeat"),
        patch("inneros_core_runtime.ops_lifecycle.emit_owner_terminal_whatsapp"),
        patch("inneros_core_runtime.productivity_metrics.record_task_completion",
              return_value={"ok": True}) as rec,
    ):
        out = asyncio.run(ta.activity_sync_mongo_mirror(envelope, "failed", {}))

    assert out["ok"] is True
    rec.assert_not_called()
