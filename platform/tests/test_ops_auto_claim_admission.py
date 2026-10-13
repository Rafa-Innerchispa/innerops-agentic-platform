"""Admission contract: ACK != claim, owner authorization must be durable."""
from inneros_core_runtime.ops_auto_claim_admission import claim_admission, pending_admission_summary


def _task(**overrides):
    t = {"task_id": "ops_123", "status": "awaiting_cursor_claim",
         "assignee": "cursor", "owner_authorized_at": "2026-10-12T20:00:00Z"}
    t.update(overrides)
    return t


def test_authorized_cursor_ready():
    assert claim_admission(_task(), provider="cursor", ready=True)["eligible"]


def test_missing_key_blocks_without_claim():
    result = claim_admission(_task(), provider="cursor", ready=False, not_ready_reason="cursor_api_key_missing")
    assert not result["eligible"]
    assert result["reason"] == "cursor_api_key_missing"


def test_payload_cannot_forge_owner_grant():
    row = _task(owner_authorized_at=None, payload={"owner_approved": True})
    assert claim_admission(row, provider="cursor", ready=True)["reason"] == "owner_authorization_not_recorded"


def test_no_reclaim_of_active_or_foreign_task():
    assert claim_admission(_task(status="in_progress", claim_token="original"), provider="cursor", ready=True)["reason"] == "already_claimed"
    assert claim_admission(_task(), provider="codex", ready=True)["reason"] == "different_assignee"


def test_manual_tasks_are_never_auto_claimed():
    assert claim_admission(_task(do_not_auto_dispatch=True), provider="cursor", ready=True)["reason"] == "manual_dispatch_only"


def test_internal_dev_swarm_proposed_only():
    row = {"task_id": "x", "assignee": "dev_swarm", "status": "proposed"}
    assert claim_admission(row, provider="dev_swarm", ready=True)["eligible"]
    assert claim_admission({**row, "status": "queued"}, provider="dev_swarm", ready=True)["reason"] == "internal_task_not_proposed"


def test_provider_agnostic_external_ide():
    row = {"task_id": "x", "assignee": "antigravity", "status": "awaiting_antigravity_claim",
           "owner_authorized_at": "2026-10-12T20:00:00Z"}
    assert claim_admission(row, provider="antigravity", ready=True)["eligible"]


def test_aggregated_blocker_report():
    rows = [_task(), _task(task_id="ops_456", owner_authorized_at=None)]
    report = pending_admission_summary(rows, provider="cursor", ready=False, not_ready_reason="cursor_api_key_missing")
    assert report["reasons"]["cursor_api_key_missing"] == 1
    assert report["reasons"]["owner_authorization_not_recorded"] == 1


def test_autopilot_does_not_forge_ide_liveness():
    from unittest.mock import patch, MagicMock
    from scripts import cursor_ops_headless_autopilot as auto
    status = {"available_slots": 0}
    with (
        patch.object(auto.lanes, "is_ha_execution_node", return_value=True),
        patch.object(auto.lanes, "touch_node_liveness"),
        patch.object(auto.lanes, "lane_status", return_value=status),
        patch.object(auto.lanes, "available_slots", return_value=0),
        patch.object(auto.cac, "cursor_api_key_status", return_value={"present": False, "source": "none"}),
        patch.object(auto, "_missing_key_alert_once", return_value={"skipped": "cooldown"}),
        patch.object(auto.cor, "list_claimable_ops_tasks", return_value={"tasks": []}),
        patch.object(auto.mongo_store, "get_db", return_value=MagicMock()),
        patch.object(auto.cep, "register_cursor_ide_session") as fake_ide,
        patch.object(auto.cep, "register_cursor_consumer_heartbeat") as fake_consumer,
    ):
        output = auto.run(auto_claim=True, execute=True, limit=1)
    fake_ide.assert_not_called()
    fake_consumer.assert_not_called()
    assert output["execution_blocker"] == "cursor_api_key_missing"


def test_spawn_failure_does_not_leave_fake_running_reservation():
    from unittest.mock import MagicMock, patch
    from scripts import cursor_ops_headless_autopilot as auto
    from inneros_core_runtime import cursor_headless_dispatch as dispatch

    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one_and_update.return_value = {
        "task_id": "ops_test",
        "headless_execution_started_at": "2026-10-12T20:00:00+00:00",
    }
    with (
        patch.object(dispatch.mongo_store, "get_db", return_value=db),
        patch(
            "inneros_core_runtime.cursor_headless_lanes.is_ha_execution_node",
            return_value=True,
        ),
        patch(
            "inneros_core_runtime.cursor_headless_lanes.available_slots",
            return_value=1,
        ),
        patch(
            "inneros_core_runtime.cursor_headless_lanes.hostname",
            return_value="ralfiia-amd",
        ),
        patch(
            "inneros_core_runtime.cursor_headless_lanes.node_role",
            return_value="amd",
        ),
        patch.object(
            dispatch.subprocess,
            "Popen",
            side_effect=FileNotFoundError("worker missing"),
        ),
    ):
        result = auto._spawn_background_execution("ops_test")
    assert result["error"] == "worker_spawn_failed"
    col.update_one.assert_called_once()
    assert "$unset" in col.update_one.call_args.args[1]


def test_resolve_workflow_id_prefers_mongo_row():
    from unittest.mock import MagicMock, patch
    from inneros_core_runtime import durable_coordination_spine as spine
    from raphiia_openai import mongo_store

    # A mock left by another test must not turn into a Temporal workflow ID.
    assert spine.resolve_workflow_id_for_task("ops_x", workflow_id="ops_task:ops_x:g2") == "ops_task:ops_x:g2"
    with patch.object(mongo_store, "get_db", return_value=MagicMock()):
        assert spine.resolve_workflow_id_for_task("ops_y") == "ops_task:ops_y"

    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    with patch.object(mongo_store, "get_db", return_value=db):
        col.find_one.return_value = {"workflow_id": " ops_task:ops_z:g3 "}
        assert spine.resolve_workflow_id_for_task("ops_z") == "ops_task:ops_z:g3"
        col.find_one.return_value = {"workflow_id": MagicMock()}
        assert spine.resolve_workflow_id_for_task("ops_z") == "ops_task:ops_z"
        col.find_one.return_value = {"workflow_id": ""}
        assert spine.resolve_workflow_id_for_task("ops_z") == "ops_task:ops_z"


def test_platform_local_headless_offers_for_phase1_correlation():
    from inneros_core_runtime import platform_local_headless_executor as plhe
    import os

    task = {
        "task_id": "ops_x",
        "correlation_id": "inneros-phase1-universal-auto-exec-20261013",
        "payload": {"task_class": "platform"},
    }
    old = os.environ.get("INNEROS_CURSOR_PLATFORM_LOCAL_EXECUTE")
    os.environ["INNEROS_CURSOR_PLATFORM_LOCAL_EXECUTE"] = "1"
    try:
        assert plhe.offers_local_execution(task)
    finally:
        if old is None:
            os.environ.pop("INNEROS_CURSOR_PLATFORM_LOCAL_EXECUTE", None)
        else:
            os.environ["INNEROS_CURSOR_PLATFORM_LOCAL_EXECUTE"] = old


def test_reap_stale_headless_unsets_lane_for_retry():
    from unittest.mock import MagicMock, patch
    from scripts import cursor_ops_headless_autopilot as auto

    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find.return_value = [
        {"task_id": "ops_stale", "headless_execution_pid": 999999},
    ]
    with (
        patch.object(auto.mongo_store, "get_db", return_value=db),
        patch.object(auto.lanes, "hostname", return_value="ralfiia-amd"),
    ):
        reaped = auto._reap_stale_headless_lanes()
    assert reaped == [{"task_id": "ops_stale", "reaped": True, "pid": 999999, "retryable": True}]
    col.update_one.assert_called_once()
    update = col.update_one.call_args.args[1]
    assert "$unset" in update
    assert "headless_execution_started_at" in update["$unset"]
    assert "headless_execution_finished_at" in update["$unset"]
    assert update["$set"]["headless_last_result"]["retryable"] is True
