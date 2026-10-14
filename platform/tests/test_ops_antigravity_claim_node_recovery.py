"""Antigravity claim node recovery regressions (ops_b4c988b85337 shape)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime import external_repair_agent as era
from inneros_core_runtime.cursor_ops_runner import _release_claim
from inneros_core_runtime.ops_awaiting_claim import awaiting_claim_status_for_task
from inneros_core_runtime.ops_interactive_recovery import (
    external_repair_may_auto_claim,
    has_active_valid_claim,
    recover_orphan_interactive_ops_tasks,
    requires_manual_interactive_lane,
)


def test_external_repair_skips_do_not_auto_dispatch() -> None:
    task = {
        "task_id": "ops_b4c988b85337",
        "assignee": "antigravity",
        "do_not_auto_dispatch": True,
        "execution_lane": "antigravity_interactive",
        "status": "proposed",
    }
    ok, reason = external_repair_may_auto_claim(task)
    assert ok is False
    assert reason == "do_not_auto_dispatch"


def test_antigravity_worktree_failure_rollback_status() -> None:
    task = {"assignee": "antigravity", "preferred_provider": "antigravity"}
    assert awaiting_claim_status_for_task(task) == "awaiting_antigravity_claim"
    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.return_value = task
    _release_claim(db, "ops_test_antigravity", reason="worktree_create_failed")
    update_doc = col.update_one.call_args[0][1]
    assert update_doc["$set"]["status"] == "awaiting_antigravity_claim"
    assert "claim_host" in update_doc["$unset"]


def test_active_valid_claim_not_orphan() -> None:
    from datetime import datetime, timedelta, timezone

    task = {
        "claim_token": "tok",
        "lease_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    assert has_active_valid_claim(task) is True


def test_orphan_interactive_recovery_to_awaiting_antigravity() -> None:
    task = {
        "task_id": "ops_orphan001",
        "status": "in_progress",
        "assignee": "antigravity",
        "execution_lane": "antigravity_interactive",
        "do_not_auto_dispatch": True,
    }
    assert requires_manual_interactive_lane(task) is True
    with patch("inneros_core_runtime.ops_interactive_recovery.mongo_store") as ms:
        db = MagicMock()
        ms.get_db.return_value = db
        col = MagicMock()
        db.__getitem__.return_value = col
        chain = MagicMock()
        col.find.return_value = chain
        chain.sort.return_value.limit.return_value = [task]
        out = recover_orphan_interactive_ops_tasks(limit=5)
    assert out["ok"] is True
    assert out["recovered"][0]["status"] == "awaiting_antigravity_claim"


def test_cursor_worktree_failure_still_awaiting_cursor_claim() -> None:
    task = {"assignee": "cursor", "preferred_provider": "cursor"}
    assert awaiting_claim_status_for_task(task) == "awaiting_cursor_claim"
    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.return_value = task
    _release_claim(db, "ops_cursor001", reason="worktree_create_failed")
    update_doc = col.update_one.call_args[0][1]
    assert update_doc["$set"]["status"] == "awaiting_cursor_claim"


def test_candidate_tasks_filters_manual_dispatch() -> None:
    rows = [
        {"task_id": "a", "do_not_auto_dispatch": True, "created_at": "1"},
        {"task_id": "b", "created_at": "2", "execution_lane": "manual_interactive"},
        {"task_id": "c", "created_at": "3", "correlation_id": "repair-x"},
    ]
    with patch.object(era, "_db") as dbm:
        col = MagicMock()
        dbm.return_value.__getitem__.return_value = col
        col.find.return_value.sort.return_value.limit.return_value = rows
        got = era._candidate_tasks("codex", 10)
    ids = [r["task_id"] for r in got]
    assert "a" not in ids
    assert "b" not in ids
    assert "c" in ids


def test_interactive_claim_skips_wrong_execution_host() -> None:
    from inneros_core_runtime import interactive_ops_runner as ior

    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.return_value = {
        "task_id": "ops_host001",
        "assignee": "antigravity",
        "owner_authorized_at": "2026-10-14T18:00:00+00:00",
        "payload": {"target_node": "amd"},
    }
    with (
        patch("inneros_core_runtime.interactive_ops_runner.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.cursor_headless_lanes.should_this_node_run_task", return_value=(False, "preferred_peer_alive:amd")),
    ):
        out = ior.claim_ops_task("antigravity", task_id="ops_host001")
    assert out["ok"] is False
    assert out["error"] == "execution_host_routing"
    col.find_one_and_update.assert_not_called()
