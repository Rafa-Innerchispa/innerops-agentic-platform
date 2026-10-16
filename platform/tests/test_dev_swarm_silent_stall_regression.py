"""Regression for launch-ok / zero-worker Dev Swarm silent stall (ops_92c85034a543 class)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


class _FakeCol:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def find_one(self, query: dict, projection=None):
        if "task_id" in query:
            row = self.rows.get(str(query["task_id"]))
            if not row:
                return None
            if "status" in query and isinstance(query["status"], dict):
                allowed = query["status"].get("$in") or []
                if row.get("status") not in allowed:
                    return None
            return dict(row)
        return None

    def find(self, query: dict, projection=None):
        out = []
        status_filter = query.get("status")
        for row in self.rows.values():
            if status_filter is None:
                out.append(dict(row))
                continue
            if isinstance(status_filter, str) and row.get("status") != status_filter:
                continue
            if isinstance(status_filter, dict):
                allowed = status_filter.get("$in") or []
                if row.get("status") not in allowed:
                    continue
            or_clause = query.get("$or")
            if or_clause:
                matched = False
                for clause in or_clause:
                    for key, val in clause.items():
                        if row.get(key) == val:
                            matched = True
                            break
                    if matched:
                        break
                if not matched and query.get("dev_swarm_retry_requested") and not row.get("dev_swarm_retry_requested"):
                    continue
            if query.get("dev_swarm_retry_requested") and not row.get("dev_swarm_retry_requested"):
                continue
            out.append(dict(row))
        limit = getattr(self, "_limit", None)
        class Cursor:
            def __init__(self, items):
                self.items = items

            def limit(self, n):
                self.items = self.items[:n]
                return self

            def __iter__(self):
                return iter(self.items)

        return Cursor(out)

    def update_one(self, query: dict, update: dict, upsert: bool = False):
        tid = str(query.get("task_id") or "")
        row = self.rows.setdefault(tid, {"task_id": tid})
        if "status" in query and isinstance(query["status"], dict):
            if row.get("status") not in (query["status"].get("$in") or []):
                return mock.Mock(modified_count=0, matched_count=0)
        for key, val in (update.get("$set") or {}).items():
            if "." in key:
                top, sub = key.split(".", 1)
                bucket = row.setdefault(top, {})
                if not isinstance(bucket, dict):
                    bucket = {}
                    row[top] = bucket
                bucket[sub] = val
            else:
                row[key] = val
        if update.get("$push"):
            for key, val in update["$push"].items():
                row.setdefault(key, [])
                if isinstance(row[key], list):
                    row[key].append(val)
        return mock.Mock(modified_count=1, matched_count=1)

    def count_documents(self, query: dict) -> int:
        return 0

    def update_many(self, query: dict, update: dict):
        return mock.Mock(modified_count=0)


class _FakeDb:
    def __init__(self, ops: _FakeCol, workers: _FakeCol) -> None:
        self._ops = ops
        self._workers = workers

    def __getitem__(self, name: str):
        if name == "ralfia_ops_tasks":
            return self._ops
        if name == "ralfia_dev_swarm_workers":
            return self._workers
        return _FakeCol()


@pytest.fixture
def incident_task() -> dict:
    stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    return {
        "task_id": "ops_92c85034a543",
        "title": "ACT III submission lane",
        "status": "running",
        "assignee": "dev_swarm",
        "owner": "dev_swarm",
        "execution_lane": "local_dev_swarm",
        "preferred_provider": "local-amd-5",
        "repo": "Rafa-Innerchispa/inneros-amd-act-iii",
        "work_branch": "local-agent/act3-final-submission-20261016",
        "dev_swarm_retry_requested": True,
        "dev_swarm_last_binding_ok": True,
        "dev_swarm_last_binding_at": stale,
        "evidence": {"phase": "hydrating"},
        "updated_at": stale,
    }


def test_launch_ok_without_worker_requeues_then_blocks_with_owner_notify(incident_task):
    from inneros_core_runtime import dev_swarm_dispatch_reconcile

    ops = _FakeCol()
    ops.rows[incident_task["task_id"]] = dict(incident_task)
    db = _FakeDb(ops, _FakeCol())
    now = datetime.now(timezone.utc)

    with mock.patch.object(dev_swarm_dispatch_reconcile, "LAUNCH_DISPATCH_STALL_SECONDS", 60):
        first = dev_swarm_dispatch_reconcile.reconcile_launch_dispatch_gaps(db, now=now, reason="test")
    assert first["requeued"] == 1
    row = ops.rows["ops_92c85034a543"]
    assert row["status"] == "proposed"
    assert row["dev_swarm_retry_requested"] is True

    ops.rows["ops_92c85034a543"]["status"] = "running"
    ops.rows["ops_92c85034a543"]["dev_swarm_dispatch_requeue_count"] = 1
    ops.rows["ops_92c85034a543"]["dev_swarm_last_binding_at"] = (
        now - timedelta(minutes=5)
    ).isoformat()

    notify = mock.Mock(return_value={"ok": True})
    with (
        mock.patch.object(dev_swarm_dispatch_reconcile, "LAUNCH_DISPATCH_STALL_SECONDS", 60),
        mock.patch("inneros_core_runtime.ops_lifecycle.emit_owner_terminal_whatsapp", notify),
    ):
        second = dev_swarm_dispatch_reconcile.reconcile_launch_dispatch_gaps(db, now=now, reason="test")
    assert second["failed"] == 1
    blocked = ops.rows["ops_92c85034a543"]
    assert blocked["status"] == "blocked"
    assert blocked["blocker"] == "worker_not_started"
    notify.assert_called_once()


def test_scheduler_admits_retry_requested_running_task(incident_task):
    from inneros_core_runtime import dev_swarm_scheduler as scheduler

    with mock.patch.object(
        scheduler.local_execution_plane,
        "repo_policy_status",
        return_value={"ok": True, "write_scope": "trusted"},
    ):
        ok, reason, repo = scheduler._eligible_reason(incident_task)
    assert ok is True
    assert reason == "eligible"
    assert repo is not None


def test_reconcile_capacity_state_runs_dispatch_watchdog(incident_task):
    from inneros_core_runtime import dev_swarm_scheduler as scheduler

    ops = _FakeCol()
    ops.rows[incident_task["task_id"]] = dict(incident_task)
    db = _FakeDb(ops, _FakeCol())

    with (
        mock.patch.object(scheduler, "_db", return_value=db),
        mock.patch.object(scheduler, "_state", return_value={"enabled": True, "max_concurrent": 4}),
        mock.patch.object(scheduler, "capacity_status", return_value={"recommendation": {"recommended_concurrency_total": 4}}),
        mock.patch.object(scheduler.coordination_liveness, "reconcile_coordination_liveness", return_value={"ok": True}),
        mock.patch.object(scheduler, "_expire_inactive_locks", return_value={"expired": 0, "preserved_active": 0}),
        mock.patch.object(scheduler, "_reconcile_stale_ops_tasks", return_value=0),
        mock.patch.object(scheduler.dev_swarm_dispatch_reconcile, "LAUNCH_DISPATCH_STALL_SECONDS", 60),
    ):
        out = scheduler.reconcile_capacity_state(reason="unit_test")
    assert out["launch_dispatch_reconcile"]["requeued"] == 1
