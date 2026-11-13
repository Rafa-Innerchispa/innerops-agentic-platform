from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from inneros_core_runtime import cursor_ops_runner as cor


def _mock_db(task=None):
    col = MagicMock()
    db = MagicMock()
    db.__getitem__.return_value = col
    if task is not None:
        col.find_one.return_value = task
    return db, col


def _future_iso(seconds=300):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _past_iso(seconds=300):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def test_release_increments_failure_counter_and_sets_backoff():
    task = {"task_id": "ops_f1", "assignee": "cursor"}
    db, col = _mock_db(task)
    cor._release_claim(db, "ops_f1", reason="worktree_create_failed", details={"ok": False})

    assert col.update_one.call_count == 1
    update = col.update_one.call_args.args[1]
    assert update["$inc"]["consecutive_claim_failures"] == 1
    assert update["$set"]["status"] == "awaiting_cursor_claim"
    backoff_until = update["$set"]["claim_backoff_until"]
    assert datetime.fromisoformat(backoff_until) > datetime.now(timezone.utc)


def test_release_fifth_failure_trips_to_human_review_and_alerts():
    task = {"task_id": "ops_f5", "assignee": "codex", "consecutive_claim_failures": 4}
    db, col = _mock_db(task)
    with patch(
        "inneros_core_runtime.notifications.ops_task_alerts.notify_claim_failures_exhausted",
        return_value={"ok": True},
    ) as alert:
        cor._release_claim(db, "ops_f5", reason="worktree_create_failed", details={})

    update = col.update_one.call_args.args[1]
    assert update["$set"]["status"] == "pending_human_review"
    assert "worktree_create_failed" in update["$set"]["claim_error"]
    assert "claim_failures_exhausted" in update["$set"]["claim_error"]
    assert update["$inc"]["consecutive_claim_failures"] == 1
    alert.assert_called_once()
    assert alert.call_args.args[0]["task_id"] == "ops_f5"


def test_release_below_trip_keeps_awaiting_and_no_alert():
    task = {"task_id": "ops_f2", "assignee": "codex", "consecutive_claim_failures": 1}
    db, col = _mock_db(task)
    with patch(
        "inneros_core_runtime.notifications.ops_task_alerts.notify_claim_failures_exhausted",
        return_value={"ok": True},
    ) as alert:
        cor._release_claim(db, "ops_f2", reason="worktree_create_failed", details={})

    update = col.update_one.call_args.args[1]
    assert update["$set"]["status"] == "awaiting_codex_claim"
    alert.assert_not_called()


def test_backoff_helper_blocks_future_allows_past_and_garbage():
    assert cor.claim_backoff_blocked({"claim_backoff_until": _future_iso()}) is not None
    assert cor.claim_backoff_blocked({"claim_backoff_until": _past_iso()}) is None
    assert cor.claim_backoff_blocked({}) is None
    # Corrupt data must never wedge a task forever; the trip counter still
    # bounds total failures independently of backoff parsing.
    assert cor.claim_backoff_blocked({"claim_backoff_until": "not-a-date"}) is None


def test_backoff_reports_retry_after_seconds():
    blocked = cor.claim_backoff_blocked({"claim_backoff_until": _future_iso(600)})
    assert blocked is not None
    assert 0 < blocked["retry_after_seconds"] <= 600


def test_interactive_claim_denied_during_backoff_without_cas():
    from inneros_core_runtime import interactive_ops_runner as ior

    task = {
        "task_id": "ops_b1",
        "status": "awaiting_codex_claim",
        "assignee": "codex",
        "owner_authorized_at": "2026-11-12T00:00:00+00:00",
        "claim_backoff_until": _future_iso(),
        "consecutive_claim_failures": 2,
    }
    db, col = _mock_db(task)
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = ior.claim_ops_task("codex", task_id="ops_b1", owner_approved=True)

    assert out["ok"] is False
    assert out["error"] == "claim_backoff_active"
    assert out["retry_after_seconds"] > 0
    assert out["task_id"] == "ops_b1"
    col.find_one_and_update.assert_not_called()


def test_cursor_claim_denied_during_backoff():
    task = {
        "task_id": "ops_b2",
        "status": "awaiting_cursor_claim",
        "assignee": "cursor",
        "owner_authorized_at": "2026-11-12T00:00:00+00:00",
        "claim_backoff_until": _future_iso(),
    }
    db, col = _mock_db(task)
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.cursor_ops_runner.cep.classify_cursor_execution",
              return_value={"execution_classification": "headless_ready"}),
        patch("inneros_core_runtime.cursor_headless_lanes.should_this_node_run_task",
              return_value=(True, "test")),
    ):
        out = cor.claim_ops_task(task_id="ops_b2", owner_approved=True)

    assert out["ok"] is False
    assert out["error"] == "claim_backoff_active"
    col.find_one_and_update.assert_not_called()


def test_codex_claim_denied_during_backoff():
    from inneros_core_runtime import codex_ops_runner as cox

    task = {
        "task_id": "ops_b3",
        "status": "awaiting_codex_claim",
        "assignee": "codex",
        "owner_authorized_at": "2026-11-12T00:00:00+00:00",
        "claim_backoff_until": _future_iso(),
    }
    db, col = _mock_db(task)
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = cox.claim_ops_task(task_id="ops_b3", owner_approved=True)

    assert out["ok"] is False
    assert out["error"] == "claim_backoff_active"
    col.find_one_and_update.assert_not_called()


def test_successful_claim_resets_failure_counter():
    import os
    from inneros_core_runtime import interactive_ops_runner as ior

    task = {
        "task_id": "ops_r1",
        "status": "awaiting_codex_claim",
        "assignee": "codex",
        "preferred_provider": "codex",
        "owner_authorized_at": "2026-11-12T00:00:00+00:00",
        "consecutive_claim_failures": 2,
        "claim_backoff_until": _past_iso(),
    }
    claimed = dict(task, status="claimed", claim_token="tok_r1")
    db, col = _mock_db(task)
    col.find_one_and_update.return_value = claimed
    env = dict(os.environ, INNEROS_CODEX_SPAWN_ON_CLAIM="0", INNEROS_ANTIGRAVITY_SPAWN_ON_CLAIM="0")
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.cursor_headless_lanes.should_this_node_run_task",
              return_value=(True, "test")),
        patch("inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
              return_value={"ok": True}),
        patch("inneros_core_runtime.ops_execution_state.refresh_current_execution_state"),
        patch.object(ior, "heartbeat_ops_task"),
        patch("inneros_core_runtime.ops_task_requirements.process_checkpoint_amendments",
              return_value={"ok": True}),
        patch.dict(os.environ, env, clear=False),
    ):
        out = ior.claim_ops_task("codex", task_id="ops_r1", owner_approved=True)

    assert out["ok"] is True
    update = col.find_one_and_update.call_args.args[1]
    assert update["$unset"]["consecutive_claim_failures"] == ""
    assert update["$unset"]["claim_backoff_until"] == ""
