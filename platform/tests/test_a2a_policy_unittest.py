from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import a2a_bridge
from raphiia_openai import local_execution_plane as lep


class FakeOps:
    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self.counter = 0

    def create_task(self, **kwargs):
        self.counter += 1
        task_id = f"ops_test_{self.counter}"
        self.tasks[task_id] = {
            "task_id": task_id,
            "status": "proposed",
            "evidence": {},
            **kwargs,
        }
        return {"ok": True, "task_id": task_id, "created": True}

    def get_task(self, task_id: str):
        return self.tasks.get(task_id)


class FakeStore:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def put(self, record: dict) -> None:
        self.records[record["a2a_task_id"]] = dict(record)

    def get(self, a2a_task_id: str):
        record = self.records.get(a2a_task_id)
        return dict(record) if record else None


class A2ABridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ops = FakeOps()
        self.store = FakeStore()
        self.bridge = a2a_bridge.A2ABridge(ops=self.ops, store=self.store)

    def test_five_agent_cards_exist(self) -> None:
        self.assertEqual(len(a2a_bridge.AGENT_CARDS), 5)
        self.assertEqual(
            set(a2a_bridge.AGENT_CARDS),
            {
                "inneros-orchestrator",
                "qwen-coding",
                "codex-repair",
                "integration-guardian",
                "browser-qa",
            },
        )

    def test_context_is_preserved_but_tasks_remain_unique(self) -> None:
        first = self.bridge.dispatch(
            agent_id="qwen-coding",
            title="One",
            body="Implement one",
            context_id="ctx-shared",
            protocol_task_id="a2a-task-one",
        )
        second = self.bridge.dispatch(
            agent_id="qwen-coding",
            title="Two",
            body="Implement two",
            context_id="ctx-shared",
            protocol_task_id="a2a-task-two",
        )
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(first["contextId"], "ctx-shared")
        self.assertEqual(second["contextId"], "ctx-shared")
        self.assertNotEqual(first["a2a_task_id"], second["a2a_task_id"])
        self.assertNotEqual(first["ops_task_id"], second["ops_task_id"])

    def test_completion_requires_evidence(self) -> None:
        created = self.bridge.dispatch(
            agent_id="integration-guardian",
            title="Verify",
            body="Verify implementation",
            context_id="ctx-proof",
            protocol_task_id="a2a-proof",
        )
        ops_task = self.ops.tasks[created["ops_task_id"]]
        ops_task["status"] = "completed"

        unsafe = self.bridge.task_status("a2a-proof")
        self.assertEqual(unsafe["status"]["state"], "working")
        self.assertEqual(unsafe["integrity_error"], "terminal_ops_task_missing_evidence")

        ops_task["evidence"] = {"tests": "PASS", "commit": "deadbeef"}
        safe = self.bridge.task_status("a2a-proof")
        self.assertEqual(safe["status"]["state"], "completed")
        self.assertTrue(safe["terminal"])
        self.assertEqual(safe["artifacts"][0]["parts"][0]["data"]["tests"], "PASS")


class LocalExecutionPolicyTests(unittest.TestCase):
    def test_registry_overrides_bundled_profile(self) -> None:
        repo = "Rafa-Innerchispa/innerops-agentic-platform"
        with mock.patch.object(
            lep,
            "_load_repo_profiles",
            return_value={repo: {"profile": "node-tests", "source_path": "/tmp/old"}},
        ), mock.patch.object(
            lep,
            "_registry_repo_profiles",
            return_value={
                repo: {
                    "profile": "python-tests",
                    "source_path": "/tmp/new",
                    "allowed_paths": ["platform"],
                    "package_roots": [".", "platform"],
                    "registry_backed": True,
                }
            },
        ):
            conf = lep._repo_config(repo)
        self.assertEqual(conf["profile"], "python-tests")
        self.assertEqual(conf["allowed_paths"], ["platform"])
        self.assertTrue(conf["registry_backed"])

    def test_python_profile_allows_unittest(self) -> None:
        self.assertTrue(
            lep._command_allowed(
                ["python3", "-m", "unittest", "discover", "-s", "platform/tests", "-v"],
                "python-tests",
            )
        )
        self.assertFalse(lep._command_allowed(["python3", "-c", "print('unsafe')"], "python-tests"))


if __name__ == "__main__":
    unittest.main()
