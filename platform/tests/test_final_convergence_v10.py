from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import autonomous_project_controller, dev_swarm_scheduler, integration_guardian


class FinalConvergenceV10Tests(unittest.TestCase):
    def test_main_resolution_prefers_fetched_origin_main_over_stale_local_main(self):
        fresh_sha = "f" * 40
        stale_sha = "a" * 40

        def fake_run(argv, _cwd, timeout_seconds=30):
            if argv[:3] == ["git", "fetch", "origin"]:
                return {"ok": True, "returncode": 0, "stdout": "", "stderr": "", "argv": argv}
            if argv[:3] == ["git", "rev-parse", "--verify"]:
                ref = argv[3]
                if ref == "origin/main^{commit}":
                    return {"ok": True, "returncode": 0, "stdout": fresh_sha + "\n", "stderr": "", "argv": argv}
                if ref == "main^{commit}":
                    return {"ok": True, "returncode": 0, "stdout": stale_sha + "\n", "stderr": "", "argv": argv}
            return {"ok": False, "returncode": 1, "stdout": "", "stderr": "missing", "argv": argv}

        with mock.patch.object(dev_swarm_scheduler.local_execution_plane, "_run", side_effect=fake_run):
            result = dev_swarm_scheduler._resolve_base_ref(Path("/tmp/repo"), "")

        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved_ref"], "origin/main")
        self.assertEqual(result["base_sha"], fresh_sha)
        self.assertEqual(result["attempts"][0]["candidate"], "origin/main")

    def test_explicit_non_main_branch_keeps_exact_branch_semantics(self):
        branch_sha = "b" * 40

        def fake_run(argv, _cwd, timeout_seconds=30):
            if argv[:3] == ["git", "fetch", "origin"]:
                return {"ok": True, "returncode": 0, "stdout": "", "stderr": "", "argv": argv}
            if argv[:3] == ["git", "rev-parse", "--verify"] and argv[3] == "local-agent/repair^{commit}":
                return {"ok": True, "returncode": 0, "stdout": branch_sha + "\n", "stderr": "", "argv": argv}
            return {"ok": False, "returncode": 1, "stdout": "", "stderr": "missing", "argv": argv}

        with mock.patch.object(dev_swarm_scheduler.local_execution_plane, "_run", side_effect=fake_run):
            result = dev_swarm_scheduler._resolve_base_ref(Path("/tmp/repo"), "local-agent/repair")

        self.assertTrue(result["ok"])
        self.assertTrue(result["explicit"])
        self.assertEqual(result["resolved_ref"], "local-agent/repair")
        self.assertEqual(result["base_sha"], branch_sha)

    def test_controller_runs_guardian_after_scheduler_and_executor(self):
        order: list[str] = []
        swarm = {"ok": True, "available": 3, "selected": [{"task_id": "ops_1"}], "skipped": [], "filtered": [], "active_worker_count": 1}

        def step(name, value):
            def _call(*_args, **_kwargs):
                order.append(name)
                return value
            return _call

        with mock.patch.object(autonomous_project_controller, "_ensure_scheduler_runtime_contract", return_value={"ok": True}), \
             mock.patch.object(autonomous_project_controller.a2a_controller, "controller_tick", side_effect=step("a2a", {"ok": True})), \
             mock.patch.object(autonomous_project_controller.dev_swarm_scheduler, "scheduler_tick", side_effect=step("scheduler", swarm)), \
             mock.patch.object(autonomous_project_controller.dev_swarm_scheduler, "executor_tick", side_effect=step("executor", {"ok": True, "executed": []})), \
             mock.patch.object(autonomous_project_controller.integration_guardian, "guardian_tick", side_effect=step("guardian", {"ok": True, "count": 1})), \
             mock.patch.object(autonomous_project_controller.work_liveness, "evaluate_tick", side_effect=step("liveness", {"ok": True, "stalled": False})):
            result = autonomous_project_controller.run_cycle(limit=8, executor_limit=4)

        self.assertEqual(order, ["a2a", "scheduler", "executor", "guardian", "liveness"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["executor_version"], "autonomous_impl_v10_a2a_liveness")

    def test_guardian_verifies_committed_head_while_worktree_exists(self):
        expected = "c" * 40
        with tempfile.TemporaryDirectory() as tmp:
            worker = {
                "task_id": "ops_guardian",
                "launch": {"worktree": {"worktree": tmp}},
                "executor": {
                    "status": "executed",
                    "outcome": "PASS",
                    "test_status": "PASS",
                    "files_touched": ["platform/inneros_core_runtime/example.py"],
                    "implementation_writes_product": ["platform/inneros_core_runtime/example.py"],
                    "commit": {"head": expected},
                },
            }
            with mock.patch.object(
                integration_guardian.local_execution_plane,
                "_run",
                return_value={"ok": True, "returncode": 0, "stdout": expected + "\n", "stderr": ""},
            ):
                verdict = integration_guardian.verify_worker(worker)

        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["expected_head"], expected)
        self.assertEqual(verdict["observed_head"], expected)
        self.assertEqual(verdict["reasons"], [])


if __name__ == "__main__":
    unittest.main()
