from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Force this isolated worktree's platform package ahead of the live runtime copy.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime import ide_task_bridge as bridge

FAST_MCP_AVAILABLE = importlib.util.find_spec("fastmcp") is not None


class FakeStore:
    def __init__(self):
        self.rows = {}
    def get_by_key(self, key):
        return next((v for v in self.rows.values() if v.get("idempotency_key") == key), None)
    def get(self, dispatch_id):
        row = self.rows.get(dispatch_id)
        return dict(row) if row else None
    def put(self, record):
        self.rows[record["dispatch_id"]] = dict(record)


class IdeTaskBridgeTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.created = []

    def fake_create(self, **kwargs):
        self.created.append(kwargs)
        return {"ok": True, "created": True, "task_id": "ops_test_1"}

    def test_normalizes_antigravity_alias(self):
        self.assertEqual(bridge.normalize_ide("anti-gravity"), "antigravity")
        self.assertEqual(bridge.normalize_ide("Cursor IDE"), "cursor")

    def test_rejects_unsupported_ide(self):
        out = bridge.dispatch_task(ide="random-editor", title="x", body="y", store=self.store)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "unsupported_ide")

    @patch("raphiia_openai.coordination_live.create_ops_task")
    @patch("inneros_core_runtime.ide_task_bridge._provider_status")
    def test_delivery_is_not_execution(self, provider_status, create_task):
        provider_status.return_value = {"installed": False, "headless_supported": False, "auth_ready": False, "provider_status": "unavailable"}
        create_task.side_effect = self.fake_create
        out = bridge.dispatch_task(ide="antigravity", title="Implement slice", body="Do bounded work", repo="Rafa-Innerchispa/innerops-agentic-platform", correlation_id="cid-1", idempotency_key="idem-1", store=self.store)
        self.assertTrue(out["ok"])
        self.assertEqual(out["delivery_state"], "delivered_to_inbox")
        self.assertEqual(out["execution_state"], "queued")
        self.assertEqual(out["transport"], "ide_inbox")
        self.assertEqual(len(self.created), 1)

    @patch("raphiia_openai.coordination_live.create_ops_task")
    @patch("inneros_core_runtime.ide_task_bridge._provider_status")
    def test_idempotent_dispatch_does_not_duplicate_ops_task(self, provider_status, create_task):
        provider_status.return_value = {"installed": False, "headless_supported": False, "auth_ready": False}
        create_task.side_effect = self.fake_create
        first = bridge.dispatch_task(ide="cursor", title="Task", body="Body", correlation_id="cid", idempotency_key="same", store=self.store)
        second = bridge.dispatch_task(ide="cursor", title="Task", body="Body", correlation_id="cid", idempotency_key="same", store=self.store)
        self.assertTrue(first["created"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(len(self.created), 1)
        self.assertEqual(first["dispatch_id"], second["dispatch_id"])

    @patch("raphiia_openai.coordination_live.create_ops_task")
    @patch("raphiia_openai.coordination_live.update_ops_task_state")
    @patch("inneros_core_runtime.ide_task_bridge._provider_status")
    def test_claim_running_complete_require_evidence(self, provider_status, update_state, create_task):
        provider_status.return_value = {"installed": False, "headless_supported": False, "auth_ready": False}
        create_task.side_effect = self.fake_create
        update_state.return_value = {"ok": True}
        dispatched = bridge.dispatch_task(ide="gemini", title="Task", body="Body", correlation_id="cid-z", store=self.store)
        did = dispatched["dispatch_id"]
        claimed = bridge.claim_task(did, "gemini", store=self.store)
        self.assertEqual(claimed["execution_state"], "claimed")
        running = bridge.mark_running(did, "gemini", store=self.store)
        self.assertEqual(running["execution_state"], "running")
        no_evidence = bridge.complete_task(did, "gemini", evidence={}, store=self.store)
        self.assertFalse(no_evidence["ok"])
        done = bridge.complete_task(did, "gemini", evidence={"tests": "PASS", "commit": "abc"}, store=self.store)
        self.assertTrue(done["ok"])
        self.assertEqual(done["execution_state"], "completed")
        self.assertTrue(done["terminal"])

    @patch("raphiia_openai.coordination_live.create_ops_task")
    @patch("inneros_core_runtime.ide_task_bridge._provider_status")
    def test_headless_ready_provider_selects_external_repair_transport(self, provider_status, create_task):
        provider_status.return_value = {"installed": True, "headless_supported": True, "auth_ready": True, "provider_status": "ready"}
        create_task.side_effect = self.fake_create
        out = bridge.dispatch_task(ide="codex", title="Repair", body="Review", store=self.store)
        self.assertEqual(out["transport"], "external_repair")

    def test_catalog_and_profile_expose_bridge_tools(self):
        from inneros_core_runtime import mcp_profiles, tool_catalog

        wanted = {
            "ide_task_bridge_status",
            "ide_dispatch_task",
            "ide_task_status",
            "ide_claim_task",
            "ide_mark_task_running",
            "ide_complete_task",
            "a2a_status",
            "a2a_agent_cards",
            "a2a_dispatch",
            "a2a_task_status",
        }
        self.assertTrue(wanted.issubset(set(tool_catalog.ALL_MCP_TOOL_NAMES)))
        for name in wanted:
            self.assertIn(name, tool_catalog.TOOL_DEFINITIONS)

        profile = mcp_profiles.get_profile("ide_task_bridge")
        self.assertTrue(profile["ok"])
        self.assertLessEqual(profile["tool_count"], 8)
        self.assertIn("ide_dispatch_task", profile["tools"])

    @unittest.skipUnless(FAST_MCP_AVAILABLE, "fastmcp is installed only in the production platform venv")
    def test_auth_scopes_expose_ide_bridge(self):
        from inneros_core_runtime.auth_middleware import TOOL_SCOPES
        self.assertEqual(TOOL_SCOPES["ide_dispatch_task"], "ralfia:agents")
        self.assertEqual(TOOL_SCOPES["ide_task_status"], "ralfia:read")

    @unittest.skipUnless(FAST_MCP_AVAILABLE, "fastmcp is installed only in the production platform venv")
    def test_fastmcp_catalog_contains_ide_bridge(self):
        from inneros_core_runtime import mcp_server
        names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
        self.assertTrue({"ide_dispatch_task", "ide_task_status", "ide_claim_task", "ide_complete_task"}.issubset(names))

    @unittest.skipUnless(FAST_MCP_AVAILABLE, "fastmcp is installed only in the production platform venv")
    def test_optional_runtime_modules_do_not_break_startup(self):
        from inneros_core_runtime import mcp_server

        self.assertEqual(mcp_server.document_vault.document_vault_status()["error"], "module_unavailable")
        self.assertEqual(mcp_server.local_model_manager.local_model_runtime_status()["error"], "module_unavailable")

    def test_acp_normalize_targets(self):
        self.assertEqual(bridge.normalize_target("CURSOR"), "cursor")
        self.assertEqual(bridge.normalize_target("chatgpt"), "gemini")

    def test_acp_delivery_not_execution(self):
        store = {}
        result = bridge.dispatch_ide_task(
            title="Probe",
            body="Hello",
            target="codex",
            correlation_id="corr-delivery-test",
            dry_run=True,
            store=store,
        )
        self.assertTrue(result["ok"])
        proj = result["execution_projection"]
        self.assertTrue(proj["delivered_to_inbox"])
        self.assertFalse(proj["running"])
        self.assertFalse(proj["completed"])
        self.assertEqual(proj["execution_state"], "delivered_to_inbox")

    def test_acp_idempotent_dispatch(self):
        store = {}
        first = bridge.dispatch_ide_task(
            title="Same",
            body="Body",
            target="cursor",
            correlation_id="corr-idem",
            dry_run=True,
            store=store,
        )
        second = bridge.dispatch_ide_task(
            title="Same",
            body="Body",
            target="cursor",
            correlation_id="corr-idem",
            dry_run=True,
            store=store,
        )
        self.assertFalse(first.get("duplicate"))
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        self.assertEqual(len(store), 1)

    def test_acp_ops_progress_distinct_from_delivery(self):
        store = {}
        dispatched = bridge.dispatch_ide_task(
            title="Run",
            body="Do",
            target="antigravity",
            correlation_id="corr-progress",
            dry_run=True,
            store=store,
        )
        key = dispatched["idempotency_key"]
        queued = dispatched["execution_projection"]["execution_state"]
        self.assertEqual(queued, "delivered_to_inbox")

        progressed = bridge.mark_ops_progress(
            store=store,
            idempotency_key=key,
            ops_status="in_progress",
            a2a_state="working",
        )
        self.assertTrue(progressed["ok"])
        self.assertEqual(progressed["execution_projection"]["execution_state"], "running")


if __name__ == "__main__":
    unittest.main()
