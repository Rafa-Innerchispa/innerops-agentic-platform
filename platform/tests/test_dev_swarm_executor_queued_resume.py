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
    }
    coll = MagicMock()
    coll.find.return_value.sort.return_value.limit.return_value = [queued_worker]
    with patch.object(dss, "_db", return_value={dss.WORKERS_COL: coll}), patch.object(
        dss, "_execute_existing_worker_generic", return_value={"ok": True, "task_id": "ops_test"}
    ) as execute:
        out = dss.executor_tick(limit=1, dry_run=False)
    assert out["ok"] is True
    assert len(out["executed"]) == 1
    execute.assert_called_once()
