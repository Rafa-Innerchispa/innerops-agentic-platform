from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import a2a_agent_registry, a2a_bridge, a2a_controller, autonomous_project_controller, dev_swarm_scheduler, work_liveness


class _CountCollection:
    def __init__(self, count: int):
        self.count = count

    def count_documents(self, _query):
        return self.count


class AutonomousControllerTests(unittest.TestCase):
    def test_a2a_cards_are_projected_from_catalog_and_ag25_is_root(self):
        agents = [
            {"agent_id": "AG-25", "display_name": "RalfIA", "role": "root", "domain": "platform", "entry_tool": "ralfia_dispatch"},
            {"agent_id": "AG-55", "display_name": "Browser Ops", "role": "browser", "domain": "platform", "entry_tool": "invoke_agent", "task_kind": "browser"},
        ]
        with mock.patch.object(a2a_agent_registry, "_catalog_snapshot", return_value=(agents, "runtime_verified")):
            cards = a2a_agent_registry.catalog_agent_cards("1.0", "test")
        self.assertEqual(set(cards), {"AG-25", "AG-55"})
        self.assertTrue(cards["AG-25"]["metadata"]["root_orchestrator"])
        self.assertTrue(cards["AG-25"]["metadata"]["runnable"])
        self.assertFalse(cards["AG-55"]["metadata"]["root_orchestrator"])

    def test_bridge_accepts_dynamic_ag_agent(self):
        agents = [{"agent_id": "AG-25", "display_name": "RalfIA", "role": "root", "domain": "platform", "entry_tool": "ralfia_dispatch"}]
        with mock.patch.object(a2a_agent_registry, "_catalog_snapshot", return_value=(agents, "runtime_verified")):
            cards = a2a_bridge._all_cards()
        self.assertIn("AG-25", cards)
        self.assertEqual(cards["AG-25"]["metadata"]["inneros_role"], "root_orchestrator")

    def test_inneros_runtime_is_product_code_prefix(self):
        self.assertIn("inneros_core_runtime/", dev_swarm_scheduler.PRODUCT_PREFIXES)
        self.assertIn("platform/inneros_core_runtime/", dev_swarm_scheduler.PRODUCT_PREFIXES)
        self.assertEqual(dev_swarm_scheduler.EXECUTOR_VERSION, "autonomous_impl_v10_a2a_liveness")

    def test_a2a_runner_timeout_does_not_block_root_controller(self):
        class FakeFuture:
            def result(self, timeout):
                raise a2a_controller.FutureTimeout()

            def cancel(self):
                return True

        class FakePool:
            def __init__(self, *args, **kwargs):
                self.shutdown_args = None

            def submit(self, *args, **kwargs):
                return FakeFuture()

            def shutdown(self, **kwargs):
                self.shutdown_args = kwargs

        with mock.patch.object(a2a_controller, "ThreadPoolExecutor", FakePool):
            result = a2a_controller._invoke_agent_bounded("AG-20", "probe", 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "agent_execution_timeout")
        self.assertEqual(result["timeout_seconds"], 1)

    def test_liveness_escalates_repeated_zero_worker_stall(self):
        db = {work_liveness.coordination_live.OPS_TASKS_COL: _CountCollection(7)}
        state = {"ok": True, "state": {"stall_streak": 1}}
        with mock.patch.object(work_liveness.mongo_store, "get_db", return_value=db), \
             mock.patch.object(work_liveness.mongo_store, "get_coordination_state", return_value=state), \
             mock.patch.object(work_liveness.mongo_store, "upsert_coordination_state", return_value={"ok": True}), \
             mock.patch.object(work_liveness.dev_swarm_watchdog, "record_anomaly", return_value={"ok": True, "task_id": "ops_watchdog"}) as anomaly:
            result = work_liveness.evaluate_tick(
                available=4,
                selected=[],
                skipped=[{"reason": "repo_policy_denied:write_scope"}],
                filtered=[],
                dry_run=False,
            )
        self.assertTrue(result["remediation_required"])
        self.assertEqual(result["stall_streak"], 2)
        self.assertEqual(result["actionable_candidate_count"], 1)
        self.assertEqual(result["skip_reasons"]["repo_policy_denied:write_scope"], 1)
        anomaly.assert_called_once()

    def test_liveness_does_not_escalate_non_dev_or_missing_metadata_backlog(self):
        db = {work_liveness.coordination_live.OPS_TASKS_COL: _CountCollection(4610)}
        state = {"ok": True, "state": {"stall_streak": 1}}
        with mock.patch.object(work_liveness.mongo_store, "get_db", return_value=db), \
             mock.patch.object(work_liveness.mongo_store, "get_coordination_state", return_value=state), \
             mock.patch.object(work_liveness.mongo_store, "upsert_coordination_state", return_value={"ok": True}), \
             mock.patch.object(work_liveness.dev_swarm_watchdog, "record_anomaly") as anomaly:
            result = work_liveness.evaluate_tick(
                available=4,
                selected=[],
                skipped=[{"reason": "repo_not_inferred"}],
                filtered=[{"reason": "non_development_ops_filtered"}],
                dry_run=False,
            )
        self.assertFalse(result["stalled"])
        self.assertFalse(result["remediation_required"])
        self.assertEqual(result["stall_streak"], 0)
        self.assertEqual(result["actionable_candidate_count"], 0)
        anomaly.assert_not_called()

    def test_controller_runs_all_four_control_stages(self):
        swarm = {"ok": True, "available": 3, "selected": [{"task_id": "ops_1"}], "skipped": [], "filtered": [], "active_worker_count": 1}
        with mock.patch.object(autonomous_project_controller, "_ensure_scheduler_runtime_contract", return_value={"ok": True}), \
             mock.patch.object(autonomous_project_controller.a2a_controller, "controller_tick", return_value={"ok": True, "count": 1}) as a2a, \
             mock.patch.object(autonomous_project_controller.integration_guardian, "guardian_tick", return_value={"ok": True, "count": 1}) as guardian, \
             mock.patch.object(autonomous_project_controller.dev_swarm_scheduler, "scheduler_tick", return_value=swarm) as scheduler, \
             mock.patch.object(autonomous_project_controller.dev_swarm_scheduler, "executor_tick", return_value={"ok": True, "executed": []}) as executor, \
             mock.patch.object(autonomous_project_controller.work_liveness, "evaluate_tick", return_value={"ok": True, "stalled": False}) as liveness:
            result = autonomous_project_controller.run_cycle(limit=8, executor_limit=4)
        self.assertTrue(result["ok"])
        self.assertEqual(result["controller"], "AG-25")
        self.assertEqual(result["transport"], "a2a+mcp-racb")
        a2a.assert_called_once()
        guardian.assert_called_once()
        scheduler.assert_called_once()
        executor.assert_called_once()
        liveness.assert_called_once()


if __name__ == "__main__":
    unittest.main()
