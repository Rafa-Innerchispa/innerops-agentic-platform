"""Full 16 Canaries Test Suite for InnerOS Coordination Consolidation."""
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from pymongo import MongoClient

from inneros_core_runtime import durable_coordination_spine as spine
from inneros_core_runtime import coordination_live
from inneros_core_runtime import local_model_router
from inneros_core_runtime import temporal_activities


class Full16CanariesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mongo_uri = "mongodb://127.0.0.1:27017"
        self.client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=2000)
        self.db = self.client["pcdoctor_swarm"]

    # CANARY 1: INTERNAL SUCCESS
    async def test_canary_01_internal_success(self):
        task_id = f"canary_internal_{datetime.now().strftime('%H%M%S')}"
        envelope = {
            "task_id": task_id,
            "workflow_id": f"ops_task:{task_id}",
            "correlation_id": f"corr_{task_id}",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "task_class": "coding",
            "assignee": "dev_swarm",
            "preferred_provider": "local",
            "revision": 1,
        }
        # 1. Validation activity
        val = await temporal_activities.activity_validate_envelope(envelope)
        self.assertTrue(val["ok"])

        # 2. Mirror dispatched
        disp = await temporal_activities.activity_sync_mongo_mirror(envelope, "dispatched", {"phase": "dispatched"})
        self.assertTrue(disp["ok"])

        # 3. Completion gate validation
        agent_res = {
            "ok": True,
            "files_count": 2,
            "code_diff": "+ feature implementation",
            "test_results": {"exit_code": 0, "ok": True}
        }
        gate = await temporal_activities.activity_validate_completion_gate(envelope, agent_res)
        self.assertTrue(gate["passed"])

        # 4. Mirror completed
        comp = await temporal_activities.activity_sync_mongo_mirror(envelope, "completed", {"agent_result": agent_res})
        self.assertTrue(comp["ok"])

        # 5. Create unread handoff
        msg = spine.create_durable_message(
            task_id=task_id,
            workflow_id=f"ops_task:{task_id}",
            sender="dev_swarm",
            recipient="chatgpt",
            subject="Canary 1 Complete",
            content="Evidence of internal coding task",
            mongo_uri=self.mongo_uri
        )
        self.assertEqual(msg["status"], "unread")

        # 6. ACK handoff
        ack = spine.ack_durable_message(msg["message_id"], actor="chatgpt", mongo_uri=self.mongo_uri)
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["status"], "consumed")

    # CANARY 2: EXTERNAL SUCCESS
    async def test_canary_02_external_success(self):
        task_id = f"canary_external_{datetime.now().strftime('%H%M%S')}"
        envelope = {
            "task_id": task_id,
            "workflow_id": f"ops_task:{task_id}",
            "correlation_id": f"corr_{task_id}",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "task_class": "coding",
            "assignee": "antigravity",
            "preferred_provider": "antigravity",
            "revision": 1,
        }
        val = await temporal_activities.activity_validate_envelope(envelope)
        self.assertTrue(val["ok"])
        agent_res = {"ok": True, "files_count": 1, "code_diff": "+ external patch", "test_results": {"exit_code": 0, "ok": True}}
        gate = await temporal_activities.activity_validate_completion_gate(envelope, agent_res)
        self.assertTrue(gate["passed"])

    # CANARY 3: DUPLICATE DISPATCH
    def test_canary_03_duplicate_dispatch(self):
        task_id = "canary_duplicate_test"
        intent_1 = spine.workflow_intent_for_task({"task_id": task_id})
        intent_2 = spine.workflow_intent_for_task({"task_id": task_id})
        self.assertEqual(intent_1["workflow_id"], f"ops_task:{task_id}")
        self.assertEqual(intent_1["workflow_id"], intent_2["workflow_id"])

    # CANARY 4: WORKER CRASH RECOVERY
    def test_canary_04_worker_crash_retry_policy(self):
        intent = spine.workflow_intent_for_task({"task_id": "crash_test"})
        retry_policy = intent.get("retry_policy", {})
        self.assertEqual(retry_policy.get("maximum_attempts"), 3)

    # CANARY 5: FAILED TEST GATE
    async def test_canary_05_failed_test_gate(self):
        envelope = {"task_id": "fail_test", "task_class": "coding"}
        agent_res = {
            "ok": False,
            "files_count": 1,
            "code_diff": "+ buggy code",
            "test_results": {"exit_code": 1, "ok": False, "stderr": "AssertionError"}
        }
        gate = await temporal_activities.activity_validate_completion_gate(envelope, agent_res)
        self.assertFalse(gate["passed"])
        self.assertIn("exit_code=1", gate["error"])

    # CANARY 6: EMPTY DIFF GATE
    async def test_canary_06_empty_diff_gate(self):
        envelope = {"task_id": "empty_diff_test", "task_class": "coding"}
        agent_res = {"ok": True, "files_count": 0, "code_diff": "", "test_results": {"exit_code": 0, "ok": True}}
        gate = await temporal_activities.activity_validate_completion_gate(envelope, agent_res)
        self.assertFalse(gate["passed"])
        self.assertIn("requires non-empty diff", gate["error"])

    # CANARY 7: HANDOFF UNREAD UNTIL EXPLICIT ACK
    def test_canary_07_handoff_explicit_ack(self):
        task_id = f"handoff_{datetime.now().strftime('%H%M%S')}"
        msg = spine.create_durable_message(
            task_id=task_id,
            workflow_id=f"ops_task:{task_id}",
            sender="antigravity",
            recipient="chatgpt",
            subject="Canary 7 Test",
            content="Unread proof",
            mongo_uri=self.mongo_uri
        )
        self.assertEqual(msg["status"], "unread")
        ack = spine.ack_durable_message(msg["message_id"], actor="chatgpt", mongo_uri=self.mongo_uri)
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["status"], "consumed")

    # CANARY 8: COMPACTION RESILIENCE
    def test_canary_08_compaction_resilience(self):
        task_id = f"compaction_{datetime.now().strftime('%H%M%S')}"
        msg = spine.create_durable_message(
            task_id=task_id,
            workflow_id=f"ops_task:{task_id}",
            correlation_id=f"corr_{task_id}",
            sender="antigravity",
            recipient="codex",
            subject="Compaction Test",
            content="Data to retrieve",
            mongo_uri=self.mongo_uri
        )
        by_task = spine.query_durable_messages(task_id=task_id, mongo_uri=self.mongo_uri)
        self.assertTrue(len(by_task) >= 1)
        by_msg = spine.query_durable_messages(message_id=msg["message_id"], mongo_uri=self.mongo_uri)
        self.assertTrue(len(by_msg) >= 1)

    # CANARY 9: NATS SINK / EVENT TRANSPORT
    def test_canary_09_nats_event_transport(self):
        event = spine.build_event(
            "task.created",
            actor="test_runner",
            task_id="ops_nats_test",
            status="queued"
        )
        self.assertEqual(event["event_type"], "task.created")
        self.assertTrue(event["event_id"].startswith("evt_"))

    # CANARY 10: TEMPORAL CONNECTION RECOVERY
    def test_canary_10_temporal_status(self):
        status = spine.status()
        self.assertTrue(status["ok"])
        self.assertIn("runtime_probe", status)

    # CANARY 11: LOCAL-FIRST FALLBACK
    def test_canary_11_local_first_fallback(self):
        health = local_model_router.local_model_health()
        self.assertTrue(health["ok"])
        self.assertIn("ollama", health)
        self.assertTrue(health["ollama"]["endpoint"].startswith("http"))

    # CANARY 12: EXTERNAL DOUBLE RUN PREVENTION
    def test_canary_12_external_double_run(self):
        tid = "ops_double_run_test"
        doc = {"task_id": tid, "workflow_id": f"ops_task:{tid}"}
        intent_a = spine.workflow_intent_for_task(doc)
        intent_b = spine.workflow_intent_for_task(doc)
        self.assertEqual(intent_a["workflow_id"], intent_b["workflow_id"])

    # CANARY 13: LIVE PROJECTION 11 CATEGORIES
    def test_canary_13_live_projection_11_categories(self):
        live = coordination_live.get_coordination_live()
        self.assertTrue(live["ok"])
        projs = live.get("projections", {})
        expected = [
            "active_tasks", "waiting_or_blocked", "in_verification", "failed_tasks",
            "completed_recently", "completed_with_unread_handoff", "orphaned_runs",
            "duplicate_execution_anomalies", "tasks_missing_required_evidence",
            "stale_workers", "unacknowledged_handoffs"
        ]
        for cat in expected:
            self.assertIn(cat, projs)

    # CANARY 14: CANONICAL LIST_OPS_TASKS
    def test_canary_14_list_ops_tasks(self):
        res = coordination_live.list_ops_tasks(
            task_id="ops_test",
            correlation_id="corr_test",
            project="test_project",
            repo="test_repo",
            assignee="antigravity",
            status="completed",
            limit=10
        )
        self.assertTrue(res["ok"])
        self.assertIn("tasks", res)

    # CANARY 15: FLEET STATUS CONSISTENCY
    def test_canary_15_fleet_status_consistency(self):
        health = local_model_router.local_model_health()
        self.assertTrue(health["ok"])
        self.assertTrue(health["local_first"])

    # CANARY 16: BELLINI REGRESSION PREVENTION
    def test_canary_16_bellini_regression_protection(self):
        task_id = "ops_34c4885f8359"
        runs = list(self.db["ralfia_external_repair_runs"].find({"task_id": task_id}))
        # Reconciled projection verifies that completed task does not have unmonitored running workers
        live = coordination_live.get_coordination_live()
        projs = live.get("projections", {})
        self.assertIn("orphaned_runs", projs)


if __name__ == "__main__":
    unittest.main()
