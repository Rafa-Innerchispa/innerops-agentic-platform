"""Legacy raphiia_openai scheduler must also pick up workers born phase=queued.

Regression: scheduler launch creates workers with executor.status=running and
executor.phase=queued, but executor_tick only queried executor.status in
{missing, pending, failed_retryable}, so launched workers stalled at birth
(observed live with task ops_muse_canary_20261109).
"""
from unittest.mock import MagicMock, patch

from raphiia_openai import dev_swarm_scheduler as dss


def test_executor_tick_includes_queued_running_workers_legacy():
    queued_worker = {
        "task_id": "ops_test",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "branch": "local-agent/ops_test-deadbeef",
        "status": "running",
        "executor": {"status": "running", "phase": "queued"},
    }
    coll = MagicMock()
    coll.find.return_value.sort.return_value.limit.return_value = [queued_worker]
    task_doc = {"task_id": "ops_test", "status": "proposed"}
    with patch.object(dss, "_db", return_value={dss.WORKERS_COL: coll}), patch.object(
        dss, "_task_doc", return_value=task_doc
    ), patch.object(dss, "_save_state"), patch.object(
        dss, "_execute_existing_worker_generic", return_value={"ok": True, "task_id": "ops_test"}
    ) as execute:
        out = dss.executor_tick(limit=1, dry_run=False)
    assert out["ok"] is True
    assert len(out["executed"]) == 1
    execute.assert_called_once()
    # The Mongo query itself must admit the born-queued shape.
    query = coll.find.call_args_list[0].args[0]
    clauses = query["$or"]
    assert {"executor.status": "running", "executor.phase": "queued"} in clauses
