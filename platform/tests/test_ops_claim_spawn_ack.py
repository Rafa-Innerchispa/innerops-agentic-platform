from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime.memory import agent_messages as ams

PIN = "gemini-3.7-flash-medium"


def _mock_db():
    col = MagicMock()
    db = MagicMock()
    db.__getitem__.return_value = col
    return db, col


def test_ack_dispatch_marks_open_messages_acknowledged() -> None:
    db, col = _mock_db()
    col.find.return_value.limit.return_value = [{"message_id": "m1"}, {"message_id": "m2"}]
    col.find_one.side_effect = [
        {"message_id": "m1", "target_agent": "antigravity", "status": "open"},
        {"message_id": "m2", "target_agent": "antigravity", "status": "open"},
    ]
    col.update_one.return_value = MagicMock(modified_count=1)
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = ams.ack_dispatch_messages_for_task("ops_abc123", "antigravity")

    assert out["ok"] is True
    assert out["acked"] == ["m1", "m2"]
    assert out["errors"] == []
    filt = col.find.call_args.args[0]
    assert filt["status"] == "open"
    assert filt["target_agent"] == "antigravity"
    ors = filt["$or"]
    assert {"payload.task_id": "ops_abc123"} in ors
    assert {"tags": "ops_abc123"} in ors


def test_ack_dispatch_collects_per_message_errors() -> None:
    db, col = _mock_db()
    col.find.return_value.limit.return_value = [{"message_id": "m1"}, {"message_id": "m2"}]
    col.find_one.side_effect = [
        {"message_id": "m1", "target_agent": "antigravity", "status": "open"},
        None,
    ]
    col.update_one.return_value = MagicMock(modified_count=1)
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = ams.ack_dispatch_messages_for_task("ops_abc123", "antigravity")

    assert out["ok"] is True
    assert out["acked"] == ["m1"]
    assert [e["message_id"] for e in out["errors"]] == ["m2"]


def test_ack_dispatch_never_raises_on_db_failure() -> None:
    db, col = _mock_db()
    col.find.side_effect = RuntimeError("mongo down")
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = ams.ack_dispatch_messages_for_task("ops_abc123", "antigravity")

    assert out["ok"] is False
    assert out["acked"] == []
    assert "inbox_lookup_failed" in out["error"]


def _claim_task(tid="ops_spawn1"):
    return {
        "task_id": tid,
        "status": "awaiting_antigravity_claim",
        "assignee": "antigravity",
        "preferred_provider": "antigravity",
        "owner_authorized_at": "2026-10-14T18:00:00+00:00",
    }


def _claimed_task(tid="ops_spawn1"):
    return {
        "task_id": tid,
        "status": "claimed",
        "assignee": "antigravity",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claim_token": "tok_n",
        "lease_until": "2030-01-01T00:00:00+00:00",
        "preferred_model": PIN,
        "effective_model": PIN,
        "correlation_id": "corr1",
    }


def test_claim_persists_failed_spawn_and_stays_claimed() -> None:
    from inneros_core_runtime import interactive_ops_runner as ior

    db, col = _mock_db()
    col.find_one.side_effect = [_claim_task(), _claim_task()]
    col.find_one_and_update.return_value = _claimed_task()
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch(
            "inneros_core_runtime.cursor_headless_lanes.should_this_node_run_task",
            return_value=(True, "ok"),
        ),
        patch("inneros_core_runtime.interactive_ops_runner.pinned_model", return_value=PIN),
        patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True},
        ),
        patch("inneros_core_runtime.ops_execution_state.refresh_current_execution_state"),
        patch("inneros_core_runtime.interactive_ops_runner.heartbeat_ops_task"),
        patch(
            "inneros_core_runtime.ops_task_requirements.process_checkpoint_amendments",
            return_value={},
        ),
        patch(
            "inneros_core_runtime.competition_lane_dispatch.maybe_spawn_after_claim",
            return_value=None,
        ),
        patch(
            "inneros_core_runtime.antigravity_headless_dispatch.spawn_headless_execute",
            return_value={"ok": False, "error": "no_available_slots"},
        ),
        patch(
            "inneros_core_runtime.memory.agent_messages.ack_dispatch_messages_for_task",
            return_value={"ok": True, "acked": [], "errors": []},
        ),
    ):
        out = ior.claim_ops_task("antigravity", task_id="ops_spawn1")

    assert out["ok"] is True
    assert out["headless_spawn"]["ok"] is False
    sets = [c.args[1]["$set"] for c in col.update_one.call_args_list]
    persisted = [s for s in sets if "headless_spawn_last" in s]
    assert len(persisted) == 1
    assert persisted[0]["headless_spawn_last"]["ok"] is False
    assert persisted[0]["headless_spawn_last"]["error"] == "no_available_slots"
    assert all(s.get("status") != "in_progress" for s in sets)


def test_claim_moves_to_in_progress_on_successful_spawn() -> None:
    from inneros_core_runtime import interactive_ops_runner as ior

    db, col = _mock_db()
    col.find_one.side_effect = [_claim_task(), _claim_task()]
    col.find_one_and_update.return_value = _claimed_task()
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch(
            "inneros_core_runtime.cursor_headless_lanes.should_this_node_run_task",
            return_value=(True, "ok"),
        ),
        patch("inneros_core_runtime.interactive_ops_runner.pinned_model", return_value=PIN),
        patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True},
        ),
        patch("inneros_core_runtime.ops_execution_state.refresh_current_execution_state"),
        patch("inneros_core_runtime.interactive_ops_runner.heartbeat_ops_task"),
        patch(
            "inneros_core_runtime.ops_task_requirements.process_checkpoint_amendments",
            return_value={},
        ),
        patch(
            "inneros_core_runtime.competition_lane_dispatch.maybe_spawn_after_claim",
            return_value=None,
        ),
        patch(
            "inneros_core_runtime.antigravity_headless_dispatch.spawn_headless_execute",
            return_value={"ok": True},
        ),
        patch(
            "inneros_core_runtime.memory.agent_messages.ack_dispatch_messages_for_task",
            return_value={"ok": True, "acked": [], "errors": []},
        ),
    ):
        out = ior.claim_ops_task("antigravity", task_id="ops_spawn1")

    assert out["ok"] is True
    progressed = [
        c for c in col.update_one.call_args_list if c.args[1].get("$set", {}).get("status") == "in_progress"
    ]
    assert len(progressed) == 1
    assert progressed[0].args[1]["$set"]["execution_started_at"]
    spawned = [c for c in col.update_one.call_args_list if "headless_spawn_last" in c.args[1].get("$set", {})]
    assert len(spawned) == 1
    assert progressed[0].args[0]["claim_token"] == spawned[0].args[0]["claim_token"]
    assert progressed[0].args[0]["status"] == "claimed"


def test_claim_records_dispatch_ack() -> None:
    from inneros_core_runtime import interactive_ops_runner as ior

    db, col = _mock_db()
    col.find_one.side_effect = [_claim_task(), _claim_task()]
    col.find_one_and_update.return_value = _claimed_task()
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch(
            "inneros_core_runtime.cursor_headless_lanes.should_this_node_run_task",
            return_value=(True, "ok"),
        ),
        patch("inneros_core_runtime.interactive_ops_runner.pinned_model", return_value=PIN),
        patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True},
        ),
        patch("inneros_core_runtime.ops_execution_state.refresh_current_execution_state"),
        patch("inneros_core_runtime.interactive_ops_runner.heartbeat_ops_task"),
        patch(
            "inneros_core_runtime.ops_task_requirements.process_checkpoint_amendments",
            return_value={},
        ),
        patch(
            "inneros_core_runtime.competition_lane_dispatch.maybe_spawn_after_claim",
            return_value=None,
        ),
        patch(
            "inneros_core_runtime.antigravity_headless_dispatch.spawn_headless_execute",
            return_value={"ok": True},
        ),
        patch(
            "inneros_core_runtime.memory.agent_messages.ack_dispatch_messages_for_task",
            return_value={"ok": True, "acked": ["m1"], "errors": []},
        ) as ack,
    ):
        out = ior.claim_ops_task("antigravity", task_id="ops_spawn1")

    ack.assert_called_once_with("ops_spawn1", "antigravity")
    assert out["dispatch_ack"] == {"ok": True, "acked": ["m1"], "errors": []}


def test_claim_persists_spawn_exception_instead_of_swallowing() -> None:
    from inneros_core_runtime import interactive_ops_runner as ior

    db, col = _mock_db()
    col.find_one.side_effect = [_claim_task(), _claim_task()]
    col.find_one_and_update.return_value = _claimed_task()
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch(
            "inneros_core_runtime.cursor_headless_lanes.should_this_node_run_task",
            return_value=(True, "ok"),
        ),
        patch("inneros_core_runtime.interactive_ops_runner.pinned_model", return_value=PIN),
        patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True},
        ),
        patch("inneros_core_runtime.ops_execution_state.refresh_current_execution_state"),
        patch("inneros_core_runtime.interactive_ops_runner.heartbeat_ops_task"),
        patch(
            "inneros_core_runtime.ops_task_requirements.process_checkpoint_amendments",
            return_value={},
        ),
        patch(
            "inneros_core_runtime.competition_lane_dispatch.maybe_spawn_after_claim",
            return_value=None,
        ),
        patch(
            "inneros_core_runtime.antigravity_headless_dispatch.spawn_headless_execute",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "inneros_core_runtime.memory.agent_messages.ack_dispatch_messages_for_task",
            return_value={"ok": True, "acked": [], "errors": []},
        ),
    ):
        out = ior.claim_ops_task("antigravity", task_id="ops_spawn1")

    assert out["ok"] is True
    sets = [c.args[1]["$set"] for c in col.update_one.call_args_list]
    persisted = [s for s in sets if "headless_spawn_last" in s]
    assert len(persisted) == 1
    assert persisted[0]["headless_spawn_last"]["ok"] is False
    assert persisted[0]["headless_spawn_last"]["error"] == "antigravity_headless_spawn_failed"
    assert "boom" in (persisted[0]["headless_spawn_last"]["detail"] or "")


def test_cursor_claim_records_dispatch_ack() -> None:
    from inneros_core_runtime import cursor_ops_runner as cor

    task = {
        "task_id": "ops_cur1",
        "status": "awaiting_cursor_claim",
        "assignee": "cursor",
        "owner_authorized_at": "2026-10-14T18:00:00+00:00",
    }
    claimed = {
        "task_id": "ops_cur1",
        "status": "claimed",
        "assignee": "cursor",
        "claim_token": "tok_c",
        "lease_until": "2030-01-01T00:00:00+00:00",
        "owner_authorized_at": "2026-10-14T18:00:00+00:00",
    }
    db, col = _mock_db()
    col.find_one.return_value = task
    col.find_one_and_update.return_value = claimed
    with (
        patch.object(cor.cep, "classify_cursor_execution", return_value={"execution_classification": "partial"}),
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch(
            "inneros_core_runtime.cursor_headless_lanes.should_this_node_run_task",
            return_value=(True, "ok"),
        ),
        patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True},
        ),
        patch("inneros_core_runtime.cursor_ops_runner._publish_task_event"),
        patch("inneros_core_runtime.cursor_ops_runner.heartbeat_ops_task"),
        patch(
            "inneros_core_runtime.ops_task_requirements.process_checkpoint_amendments",
            return_value={},
        ),
        patch(
            "inneros_core_runtime.memory.agent_messages.ack_dispatch_messages_for_task",
            return_value={"ok": True, "acked": ["m9"], "errors": []},
        ) as ack,
        patch.dict("os.environ", {"INNEROS_CURSOR_SPAWN_ON_CLAIM": "0"}),
    ):
        out = cor.claim_ops_task(task_id="ops_cur1", owner_approved=True)

    assert out["ok"] is True
    ack.assert_called_once_with("ops_cur1", "cursor")
    assert out["dispatch_ack"] == {"ok": True, "acked": ["m9"], "errors": []}
