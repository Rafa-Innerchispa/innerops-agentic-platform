"""DevSwarm cumulative retry and stale-generation regression guards.

Pure offline AST checks; no production Mongo, Temporal, or model calls.
"""
import ast
from pathlib import Path
import unittest
from typing import Any

SOURCE = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "dev_swarm_scheduler.py"
TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(TEXT, filename=str(SOURCE))


def isolated(name):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    context = {
        "Any": Any,
        "MAX_AUTOMATED_TASK_DISPATCH_ATTEMPTS": 3,
        "MAX_STALE_RECLAIMS": 2,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), context)
    return context[name]


class TestCumulativeRetryBudget(unittest.TestCase):
    def test_new_and_below_budget(self):
        check = isolated("_dev_swarm_dispatch_budget_exhausted")
        self.assertFalse(check({}))
        self.assertFalse(check({"attempt_count": 2, "dev_swarm_stale_reclaim_count": 1}))

    def test_exhausted_and_malformed_fail_closed(self):
        check = isolated("_dev_swarm_dispatch_budget_exhausted")
        for task in ({"attempt_count": 3}, {"attempt_count": 80},
                     {"dev_swarm_stale_reclaim_count": 2},
                     {"attempt_count": "invalid"}):
            with self.subTest(task=task):
                self.assertTrue(check(task))

    def test_scheduler_requeue_and_direct_fanout_enforce_budget(self):
        segments = {
            n.name: ast.get_source_segment(TEXT, n) or ""
            for n in TREE.body if isinstance(n, ast.FunctionDef)
        }
        for name in ("_eligible_reason", "_safe_dev_swarm_requeue_candidate",
                     "_fanout_execute_one"):
            self.assertIn("_dev_swarm_dispatch_budget_exhausted(task)", segments[name])

    def test_stale_update_has_identity_and_heartbeat_fences(self):
        node = next(n for n in TREE.body
                    if isinstance(n, ast.FunctionDef) and n.name == "_reclaim_stale_workers")
        segment = ast.get_source_segment(TEXT, node) or ""
        for token in ('("worker_id", "last_heartbeat_at")',
                      'worker_selector["executor.last_progress_at"]',
                      'task_selector["dev_swarm_worker_id"]',
                      '"$inc": {"dev_swarm_stale_reclaim_count": 1}'):
            self.assertIn(token, segment)

    def test_blocked_ops_requeue_scan_cap_is_80(self):
        node = next(n for n in TREE.body
                    if isinstance(n, ast.FunctionDef) and n.name == "requeue_retryable_blocked_ops")
        segment = ast.get_source_segment(TEXT, node) or ""
        self.assertIn("limit: int = 80", segment)
        self.assertIn("min(int(limit or 80), 300)", segment)


if __name__ == "__main__":
    unittest.main()
