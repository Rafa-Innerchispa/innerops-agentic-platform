"""Workers stuck in executor.phase=queued must be picked up by executor_tick."""
from unittest.mock import MagicMock, patch

from inneros_core_runtime import dev_swarm_scheduler as dss


def test_executor_tick_includes_queued_running_workers():
    queued_worker = {
        "task_id": "ops_test",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "branch": "local-agent/ops_test-deadbeef",
        "status": "running",
        "executor": {"status": "running", "phase": "queued"},
        "updated_at": "2026-11-01T13:00:00+00:00",
    }
    coll = MagicMock()
    coll.find.return_value.sort.return_value.limit.return_value = [queued_worker]
    task_doc = {"task_id": "ops_test", "status": "proposed", "tags": ["local_dev_swarm"], "priority": "p1"}
    with patch.object(dss, "_db", return_value={dss.WORKERS_COL: coll}), patch.object(
        dss, "_task_doc", return_value=task_doc
    ), patch.object(dss.coordination_live, "update_ops_task_state"), patch(
        "inneros_core_runtime.execution_resource_guard.release_stale_active_reservation", return_value=False
    ), patch.object(
        dss, "_execute_existing_worker_generic", return_value={"ok": True, "task_id": "ops_test"}
    ) as execute:
        out = dss.executor_tick(limit=1, dry_run=False)
    assert out["ok"] is True
    assert len(out["executed"]) == 1
    execute.assert_called_once()


def test_executor_tick_skips_terminal_ops_task_workers():
    stale_worker = {
        "task_id": "ops_old",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "branch": "local-agent/ops_old-deadbeef",
        "status": "blocked",
        "executor": {"status": "failed_retryable", "phase": "queued"},
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    coll = MagicMock()
    coll.find.return_value.sort.return_value.limit.return_value = [stale_worker]
    coll.update_one = MagicMock()
    with patch.object(dss, "_db", return_value={dss.WORKERS_COL: coll}), patch.object(
        dss, "_task_doc", return_value={"task_id": "ops_old", "status": "cancelled"}
    ), patch.object(dss, "_execute_existing_worker_generic") as execute:
        out = dss.executor_tick(limit=1, dry_run=False)
    assert out["executed"] == []
    assert any(s.get("reason", "").startswith("task_not_executable") for s in out["skipped"])
    execute.assert_not_called()
