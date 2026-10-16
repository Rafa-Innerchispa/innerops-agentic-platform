"""Regression: launcher OK without worker must not stay running forever."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from raphiia_openai import coordination_live


def test_reconcile_false_running_blocks_orphan_hydrating():
    from inneros_core_runtime import dev_swarm_scheduler as ds
    from datetime import datetime, timezone, timedelta

    db = MagicMock()
    old = datetime.now(timezone.utc) - timedelta(seconds=600)
    task = {
        "task_id": "ops_fixture_orphan",
        "assignee": "dev_swarm",
        "owner": "dev_swarm",
        "status": "running",
        "evidence": {"phase": "hydrating"},
        "worker_dispatch_pending_at": old.isoformat(),
        "revision": 3,
        "title": "TEST orphan",
    }
    db[ds.WORKERS_COL].find_one.return_value = None
    cur = MagicMock(); cur.limit.return_value = [task]; db[coordination_live.OPS_TASKS_COL].find.return_value = cur
    db[ds.coordination_live.OPS_TASKS_COL].update_one.return_value = MagicMock(modified_count=1)
    with patch(
        "inneros_core_runtime.ops_lifecycle_notify.notify_ops_stalled_or_failed",
        return_value={"ok": True},
    ), patch(
        "inneros_core_runtime.notifications.ops_task_alerts.notify_ops_transition",
        return_value={"ok": True},
    ):
        n = ds._reconcile_false_running_ops_tasks(db, datetime.now(timezone.utc), old.isoformat(), "test")
    assert n == 1


def test_eligible_dispatch_pending_running_without_worker():
    from inneros_core_runtime import dev_swarm_scheduler as ds

    task = {
        "task_id": "ops_x",
        "status": "running",
        "assignee": "dev_swarm",
        "owner": "dev_swarm",
        "dev_swarm_retry_requested": True,
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "execution_lane": "local_dev_swarm",
        "title": "innerops test",
    }
    with patch.object(ds, "_task_has_live_worker", return_value=False), patch.object(
        ds.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "write"}
    ):
        ok, reason, repo = ds._eligible_reason(task)
    assert ok is True
    assert reason == "eligible"
