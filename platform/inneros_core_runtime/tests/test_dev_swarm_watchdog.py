from __future__ import annotations

import unittest
from copy import deepcopy

from raphiia_openai import dev_swarm_watchdog


class _Cursor(list):
    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, count):
        return _Cursor(self[:count])


class _Result:
    def __init__(self, modified_count=0, upserted_id=None):
        self.modified_count = modified_count
        self.matched_count = modified_count
        self.upserted_id = upserted_id


class _Collection:
    def __init__(self):
        self.rows = []

    def _match(self, row, query):
        for key, expected in query.items():
            actual = row.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$nin" in expected and actual in expected["$nin"]:
                    return False
                continue
            if actual != expected:
                return False
        return True

    def find_one(self, query, _projection=None):
        for row in self.rows:
            if self._match(row, query):
                return deepcopy(row)
        return None

    def find(self, query, _projection=None):
        return _Cursor(deepcopy([row for row in self.rows if self._match(row, query)]))

    def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if self._match(row, query):
                self._apply(row, update, inserting=False)
                return _Result(1)
        if not upsert:
            return _Result(0)
        row = dict(query)
        self._apply(row, update, inserting=True)
        self.rows.append(row)
        return _Result(1, upserted_id=len(self.rows))

    def insert_one(self, doc):
        self.rows.append(deepcopy(doc))
        return _Result(1, upserted_id=len(self.rows))

    def _apply(self, row, update, inserting):
        if inserting:
            row.update(deepcopy(update.get("$setOnInsert", {})))
        row.update(deepcopy(update.get("$set", {})))
        for key, value in update.get("$inc", {}).items():
            row[key] = int(row.get(key) or 0) + int(value)
        for key, value in update.get("$push", {}).items():
            current = list(row.get(key) or [])
            if isinstance(value, dict) and "$each" in value:
                current.extend(deepcopy(value["$each"]))
                if "$slice" in value:
                    current = current[value["$slice"] :]
            else:
                current.append(deepcopy(value))
            row[key] = current


class _Db(dict):
    def __missing__(self, key):
        self[key] = _Collection()
        return self[key]


def _anomaly():
    return {
        "type": "repo_routing_wrong",
        "component": "dev_swarm_scheduler",
        "task_id": "ops_test",
        "repo_expected": "Rafa-Innerchispa/innerops-agentic-platform",
        "repo_actual": "missing-project",
        "package_root": "platform",
        "profile": "inneros_platform",
        "evidence": {"reason": "test"},
    }


class DevSwarmWatchdogTests(unittest.TestCase):
    def test_fingerprint_is_stable_for_same_failure(self):
        self.assertEqual(dev_swarm_watchdog.fingerprint_anomaly(_anomaly()), dev_swarm_watchdog.fingerprint_anomaly(_anomaly()))

    def test_record_close_reopen_uses_same_task(self):
        db = _Db()
        first = dev_swarm_watchdog.record_anomaly(_anomaly(), db=db)
        second = dev_swarm_watchdog.record_anomaly(_anomaly(), db=db)
        self.assertEqual(first["repair_task"]["task_id"], second["repair_task"]["task_id"])
        self.assertEqual(len(db[dev_swarm_watchdog.OPS_TASKS_COL].rows), 1)
        close = dev_swarm_watchdog.close_anomaly(first["fingerprint"], evidence={"tests": "PASS"}, db=db)
        reopened = dev_swarm_watchdog.record_anomaly(_anomaly(), db=db)
        self.assertTrue(close["ok"])
        self.assertEqual(reopened["status"], "regression_reopened")
        self.assertEqual(len(db[dev_swarm_watchdog.OPS_TASKS_COL].rows), 1)

    def test_canonicalize_duplicate_ops_marks_duplicate_superseded(self):
        db = _Db()
        tasks = db[dev_swarm_watchdog.OPS_TASKS_COL]
        tasks.insert_one({"task_id": "ops_a", "correlation_id": "cid", "assignee": "codex", "status": "proposed", "created_at": "1"})
        tasks.insert_one({"task_id": "ops_b", "correlation_id": "cid", "assignee": "codex", "status": "proposed", "created_at": "2"})
        out = dev_swarm_watchdog.canonicalize_duplicate_ops(correlation_id="cid", canonical_task_id="ops_a", db=db)
        dup = tasks.find_one({"task_id": "ops_b"})
        self.assertTrue(out["ok"])
        self.assertEqual(dup["status"], "superseded")
        self.assertEqual(dup["superseded_by"], "ops_a")

    def test_summary_reports_open_and_regression(self):
        db = _Db()
        first = dev_swarm_watchdog.record_anomaly(_anomaly(), db=db)
        dev_swarm_watchdog.close_anomaly(first["fingerprint"], evidence={"tests": "PASS"}, db=db)
        dev_swarm_watchdog.record_anomaly(_anomaly(), db=db)
        out = dev_swarm_watchdog.summary(db=db)
        self.assertEqual(out["regression_count"], 1)
        self.assertEqual(out["open_anomaly_count"], 1)


if __name__ == "__main__":
    unittest.main()
