"""Comprehensive test suite for Coordination Liveness Supervisor."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from inneros_core_runtime import coordination_liveness


class MockCollection:
    def __init__(self):
        self.docs = []

    def find_one(self, query: dict[str, Any], projection: dict[str, Any] | None = None) -> dict[str, Any] | None:
        for d in self.docs:
            match = True
            for k, v in query.items():
                if k == "$or":
                    or_match = any(
                        all(d.get(ok) == ov for ok, ov in sub.items())
                        for sub in v
                    )
                    if not or_match:
                        match = False
                        break
                elif isinstance(v, dict):
                    if "$in" in v and d.get(k) not in v["$in"]:
                        match = False
                        break
                elif d.get(k) != v and not (v == 0 and d.get(k) is None):
                    match = False
                    break
            if match:
                return dict(d)
        return None

    def find(self, query: dict[str, Any] = None, projection: dict[str, Any] | None = None):
        res = []
        for d in self.docs:
            if not query:
                res.append(dict(d))
                continue
            match = True
            for k, v in query.items():
                if k == "$or":
                    or_match = any(
                        all(d.get(ok) == ov for ok, ov in sub.items())
                        for sub in v
                    )
                    if not or_match:
                        match = False
                        break
                elif isinstance(v, dict):
                    if "$in" in v and d.get(k) not in v["$in"]:
                        match = False
                        break
                elif d.get(k) != v and not (v == 0 and d.get(k) is None):
                    match = False
                    break
            if match:
                res.append(dict(d))
        return res

    def insert_one(self, doc: dict[str, Any]):
        self.docs.append(dict(doc))
        return MockResult(1)

    def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False):
        target = None
        for d in self.docs:
            match = True
            for k, v in query.items():
                if d.get(k) != v and not (v == 0 and d.get(k) is None):
                    match = False
                    break
            if match:
                target = d
                break
        if not target and upsert:
            target = dict(query)
            self.docs.append(target)
        if target:
            if "$set" in update:
                target.update(update["$set"])
            if "$push" in update:
                for pk, pv in update["$push"].items():
                    target.setdefault(pk, []).append(pv)
            return MockResult(1)
        return MockResult(0)


class MockResult:
    def __init__(self, modified_count: int):
        self.modified_count = modified_count
        self.upserted_id = None


class MockDB:
    def __init__(self):
        self.collections: dict[str, MockCollection] = {}

    def __getitem__(self, name: str) -> MockCollection:
        if name not in self.collections:
            self.collections[name] = MockCollection()
        return self.collections[name]


class CoordinationLivenessTests(unittest.TestCase):
    def setUp(self):
        self.mock_db = MockDB()
        self.patch_db = patch("raphiia_openai.mongo_store.get_db", return_value=self.mock_db)
        self.patch_db.start()

    def tearDown(self):
        self.patch_db.stop()

    def test_acquire_and_renew_task_lease(self):
        task_id = "ops_test_001"
        self.mock_db["ralfia_ops_tasks"].insert_one({
            "task_id": task_id,
            "title": "Test Task",
            "status": "proposed",
            "repo": "test-repo",
        })

        now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        res = coordination_liveness.acquire_task_lease(
            task_id=task_id,
            worker_id="worker_ag_01",
            actor="antigravity",
            lease_seconds=600,
            now=now,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["action"], "acquired")
        self.assertEqual(res["attempt_count"], 1)

        task = self.mock_db["ralfia_ops_tasks"].find_one({"task_id": task_id})
        self.assertEqual(task["status"], "in_progress")
        self.assertEqual(task["worker_id"], "worker_ag_01")
        self.assertEqual(task["owner"], "antigravity")

        # Renew with progress
        now_renew = now + timedelta(seconds=120)
        renew_res = coordination_liveness.renew_task_lease(
            task_id=task_id,
            worker_id="worker_ag_01",
            actor="antigravity",
            files_touched=["src/app.py"],
            tests_passed=["test_app"],
            now=now_renew,
        )
        self.assertTrue(renew_res["ok"])
        self.assertTrue(renew_res["has_progress"])
        self.assertFalse(renew_res["is_frozen"])

    def test_frozen_retry_storm_detection(self):
        task_id = "ops_storm_001"
        self.mock_db["ralfia_ops_tasks"].insert_one({
            "task_id": task_id,
            "title": "Retry Storm Task",
            "status": "in_progress",
            "worker_id": "worker_amd_01",
            "owner": "dev_swarm",
            "repo": "storm-repo",
            "attempt_count": 3,
            "retry_budget": 3,
            "no_progress_heartbeat_count": 2,
            "is_frozen": False,
            "lease_expires_at": (datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=300)).isoformat(),
        })

        now = datetime(2026, 9, 23, 12, 1, 0, tzinfo=timezone.utc)
        # 3rd heartbeat with NO progress
        renew_res = coordination_liveness.renew_task_lease(
            task_id=task_id,
            worker_id="worker_amd_01",
            actor="dev_swarm",
            next_action="Retrying again",
            blocker="quality_gate_failed",
            now=now,
        )
        self.assertTrue(renew_res["ok"])
        self.assertFalse(renew_res["has_progress"])
        self.assertTrue(renew_res["is_frozen"])

        # Reconciler should block it and release lock
        rec = coordination_liveness.reconcile_coordination_liveness(now=now, dry_run=False)
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["retry_exhausted"], 1)
        self.assertEqual(len(rec["reconciled_tasks"]), 1)

        task = self.mock_db["ralfia_ops_tasks"].find_one({"task_id": task_id})
        self.assertEqual(task["status"], "blocked")
        self.assertIn("retry_budget_exhausted_frozen", task["blocker"])

    def test_expired_lease_reconciliation(self):
        task_id = "ops_stale_001"
        t_start = datetime(2026, 9, 23, 11, 0, 0, tzinfo=timezone.utc)
        t_expired = t_start + timedelta(seconds=600)

        self.mock_db["ralfia_ops_tasks"].insert_one({
            "task_id": task_id,
            "title": "Stale Worker Task",
            "status": "in_progress",
            "worker_id": "dead_worker",
            "owner": "cursor",
            "repo": "dead-repo",
            "attempt_count": 1,
            "retry_budget": 3,
            "lease_expires_at": t_expired.isoformat(),
            "last_heartbeat_at": t_start.isoformat(),
        })

        now = datetime(2026, 9, 23, 11, 15, 0, tzinfo=timezone.utc)
        rec = coordination_liveness.reconcile_coordination_liveness(now=now, dry_run=False)
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["stale_tasks_reconciled"], 1)
        self.assertEqual(rec["reconciled_tasks"][0]["action"], "transition_to_proposed")

        task = self.mock_db["ralfia_ops_tasks"].find_one({"task_id": task_id})
        self.assertEqual(task["status"], "proposed")
        self.assertIsNone(task["worker_id"])

    def test_orphan_lock_release(self):
        task_id = "ops_done_001"
        repo = "orphan-repo"

        self.mock_db["ralfia_ops_tasks"].insert_one({
            "task_id": task_id,
            "title": "Completed Task",
            "status": "completed",
        })
        self.mock_db["ralfia_coordination_locks"].insert_one({
            "resource_id": repo,
            "status": "active",
            "task_id": task_id,
            "owner": "codex",
            "revision": 1,
            "expires_at": (datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=3600)).isoformat(),
        })

        now = datetime(2026, 9, 23, 12, 5, 0, tzinfo=timezone.utc)
        rec = coordination_liveness.reconcile_coordination_liveness(now=now, dry_run=False)
        self.assertTrue(rec["ok"])
        self.assertIn(repo, rec["orphan_locks_released"])

        lock = self.mock_db["ralfia_coordination_locks"].find_one({"resource_id": repo})
        self.assertEqual(lock["status"], "released")


if __name__ == "__main__":
    unittest.main()
