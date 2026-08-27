from pathlib import Path
import sys
import unittest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import a2a_bridge


class FakeOps:
    def __init__(self):
        self.tasks = {}
        self.seq = 0

    def create_task(self, **kwargs):
        self.seq += 1
        task_id = f"ops_fake_{self.seq}"
        task = {
            "task_id": task_id,
            "correlation_id": kwargs["correlation_id"],
            "assignee": kwargs["assignee"],
            "title": kwargs["title"],
            "status": "proposed",
            "evidence": {},
        }
        self.tasks[task_id] = task
        return {"ok": True, "created": True, "task_id": task_id, "task": task}

    def get_task(self, task_id):
        task = self.tasks.get(task_id)
        return dict(task) if task else None


class FakeStore:
    def __init__(self):
        self.records = {}

    def put(self, record):
        self.records[record["a2a_task_id"]] = dict(record)

    def get(self, a2a_task_id):
        record = self.records.get(a2a_task_id)
        return dict(record) if record else None


class A2ABridgeTests(unittest.TestCase):
    def setUp(self):
        self.ops = FakeOps()
        self.store = FakeStore()
        self.bridge = a2a_bridge.A2ABridge(ops=self.ops, store=self.store)

    def test_five_stable_agent_cards_exist(self):
        self.assertEqual(
            set(a2a_bridge.AGENT_CARDS),
            {"inneros-orchestrator", "qwen-coding", "codex-repair", "integration-guardian", "browser-qa"},
        )
        self.assertEqual(a2a_bridge.A2A_PROTOCOL_VERSION, "1.0")
        for card in a2a_bridge.AGENT_CARDS.values():
            self.assertTrue(card["name"])
            self.assertTrue(card["skills"])
            self.assertEqual(card["protocolVersion"], a2a_bridge.A2A_PROTOCOL_VERSION)

    def test_dispatch_preserves_context_and_creates_real_ops_contract(self):
        result = self.bridge.dispatch(
            agent_id="qwen-coding",
            title="Implement bounded feature",
            body="Work only in the approved repo and return test evidence.",
            correlation_id="ctx-123",
            priority="p0",
            dry_run=False,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["contextId"], "ctx-123")
        self.assertEqual(result["state"], "submitted")
        self.assertEqual(result["assignee"], "ralfia")
        task = self.ops.get_task(result["ops_task_id"])
        self.assertEqual(task["correlation_id"], "ctx-123")
        self.assertIn("[A2A:qwen-coding]", task["title"])

    def test_dry_run_does_not_persist(self):
        result = self.bridge.dispatch(
            agent_id="browser-qa",
            title="Review preview",
            body="Inspect approved local preview.",
            correlation_id="ctx-dry",
            dry_run=True,
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.ops.tasks, {})
        self.assertEqual(self.store.records, {})

    def test_unknown_agent_fails_closed(self):
        result = self.bridge.dispatch(agent_id="imaginary", title="x", body="y")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_a2a_agent")

    def test_ops_lifecycle_projects_to_a2a_monotonically(self):
        submitted = self.bridge.dispatch(
            agent_id="inneros-orchestrator",
            title="Coordinate",
            body="Coordinate one durable task.",
            correlation_id="ctx-life",
        )
        a2a_id = submitted["a2a_task_id"]
        ops_id = submitted["ops_task_id"]

        first = self.bridge.task_status(a2a_id)
        self.assertEqual(first["status"]["state"], "submitted")
        self.assertFalse(first["terminal"])

        self.ops.tasks[ops_id]["status"] = "in_progress"
        working = self.bridge.task_status(a2a_id)
        self.assertEqual(working["status"]["state"], "working")

        self.ops.tasks[ops_id]["status"] = "blocked"
        blocked = self.bridge.task_status(a2a_id)
        self.assertEqual(blocked["status"]["state"], "input-required")

    def test_completed_is_rejected_without_inneros_evidence(self):
        submitted = self.bridge.dispatch(
            agent_id="integration-guardian",
            title="Verify",
            body="Verify test evidence.",
            correlation_id="ctx-no-evidence",
        )
        ops_id = submitted["ops_task_id"]
        self.ops.tasks[ops_id]["status"] = "completed"
        self.ops.tasks[ops_id]["evidence"] = {}
        status = self.bridge.task_status(submitted["a2a_task_id"])
        self.assertEqual(status["status"]["state"], "working")
        self.assertEqual(status["integrity_error"], "terminal_ops_task_missing_evidence")
        self.assertFalse(status["terminal"])

    def test_completed_propagates_evidence_as_artifact(self):
        submitted = self.bridge.dispatch(
            agent_id="integration-guardian",
            title="Verify",
            body="Verify test evidence.",
            correlation_id="ctx-evidence",
        )
        ops_id = submitted["ops_task_id"]
        self.ops.tasks[ops_id]["status"] = "completed"
        self.ops.tasks[ops_id]["evidence"] = {"status": "PASS", "tests": ["7 passed"]}
        status = self.bridge.task_status(submitted["a2a_task_id"])
        self.assertEqual(status["status"]["state"], "completed")
        self.assertTrue(status["terminal"])
        self.assertEqual(status["artifacts"][0]["parts"][0]["data"]["status"], "PASS")

    def test_codex_card_keeps_external_gate_metadata(self):
        card = a2a_bridge.AGENT_CARDS["codex-repair"]
        self.assertTrue(card["metadata"]["external"])
        self.assertTrue(card["metadata"]["approval_gated"])
        self.assertEqual(card["metadata"]["assignee"], "codex")

    def test_protocol_task_id_and_context_id_are_preserved(self):
        result = self.bridge.dispatch(
            agent_id="qwen-coding",
            title="Implement official A2A task",
            body="Keep the A2A wire identity stable.",
            context_id="ctx-official",
            protocol_task_id="task-official-1",
            dry_run=False,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["a2a_task_id"], "task-official-1")
        self.assertEqual(result["contextId"], "ctx-official")
        task = self.ops.get_task(result["ops_task_id"])
        self.assertEqual(task["correlation_id"], "a2a:ctx-official:task-official-1")

    def test_two_tasks_in_same_a2a_context_do_not_dedupe_each_other(self):
        first = self.bridge.dispatch(
            agent_id="qwen-coding",
            title="First",
            body="First task in shared context.",
            context_id="ctx-shared",
            protocol_task_id="task-shared-1",
        )
        second = self.bridge.dispatch(
            agent_id="qwen-coding",
            title="Second",
            body="Second task in shared context.",
            context_id="ctx-shared",
            protocol_task_id="task-shared-2",
        )
        self.assertNotEqual(first["ops_task_id"], second["ops_task_id"])
        self.assertNotEqual(
            self.ops.get_task(first["ops_task_id"])["correlation_id"],
            self.ops.get_task(second["ops_task_id"])["correlation_id"],
        )


if __name__ == "__main__":
    unittest.main()
