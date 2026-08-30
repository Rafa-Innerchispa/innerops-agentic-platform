"""Regression tests for AG-52 ISKCON intent-aware operations."""
from __future__ import annotations

import unittest
from unittest import mock

from inneros_core_runtime import module_contract
from inneros_core_runtime.agents import ag49_local_dispatcher as dispatcher
from inneros_core_runtime.agents import ag52_iskcon_ops_agent as ag52
from inneros_core_runtime.agents import pool_agent_runners
from inneros_core_runtime import mcp_profiles
from inneros_core_runtime.mcp_catalog import tool_catalog


class AG52IskconOpsTests(unittest.TestCase):
    def test_module_manifest_is_tenant_scoped_and_has_no_lan_urls(self) -> None:
        result = ag52.agent_iskcon_module_manifest()
        self.assertTrue(result["ok"])
        manifest = result["manifest"]
        self.assertEqual(manifest["tenant_id"], "ent_iskcon")
        self.assertEqual(manifest["module_id"], "iskcon_ops")
        self.assertIn("https://iskcon.creatorcore.ai", manifest["entrypoints"]["public"])
        self.assertNotIn("192.168.", repr(manifest))
        statuses = {spec["status"] for spec in manifest["aria"]["capabilities"].values()}
        self.assertTrue({"LIVE", "PARTIAL", "NOT_READY"}.issuperset(statuses))

    def test_emergency_plan_intent_returns_real_artifact_contract(self) -> None:
        result = ag52.agent_iskcon_dispatch(
            "intent",
            "Hazme un plan de emergencia para el templo el domingo",
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["contract"], "module_action_v1")
        self.assertEqual(result["tenant_id"], "ent_iskcon")
        self.assertEqual(result["module_id"], "iskcon_ops")
        self.assertEqual(result["intent"], "emergency_plan")
        self.assertEqual(result["artifact"]["kind"], "pdf")
        self.assertEqual(result["artifact"]["download_policy"], "tenant_scoped")
        self.assertFalse(result["approval"]["required"])

    def test_module_action_blocks_cross_tenant(self) -> None:
        result = module_contract.route_module_action(
            tenant_id="ent_pcdoctor",
            module_id="iskcon_ops",
            intent="emergency_plan",
            inputs={"scenario": "test"},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 403)

    def test_not_ready_action_does_not_fake_success(self) -> None:
        result = module_contract.route_module_action(
            tenant_id="ent_iskcon",
            module_id="iskcon_ops",
            intent="temple_checklist",
            inputs={"area": "altar"},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "action_not_ready")
        self.assertEqual(result["status"], "NOT_READY")

    def test_artifact_download_cross_tenant_forbidden(self) -> None:
        class Artifacts:
            def find_one(self, *_args, **_kwargs):
                return {"artifact_id": "a1", "tenant_id": "ent_iskcon", "kind": "draft"}

        class Db(dict):
            def __getitem__(self, key):
                return Artifacts()

        with mock.patch.object(module_contract, "_db", return_value=Db()):
            result = module_contract.download_module_artifact("ent_pcdoctor", "a1")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "cross_tenant_forbidden")
        self.assertEqual(result["status_code"], 403)

    def test_yoga_whatsapp_intent_generates_draft_contract(self) -> None:
        result = ag52.agent_iskcon_dispatch(
            "intent",
            "Automatiza el canal de WhatsApp de yoga con dos mensajes diarios vaishnavas",
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "yoga_whatsapp_campaign")
        self.assertEqual(result["channel"], "whatsapp_yoga")
        self.assertEqual(result["frequency"], "2_per_day")
        self.assertEqual(result["draft_count"], 14)
        self.assertFalse(result["send_ready"])
        self.assertTrue(result["requires_approval"])

    def test_class_update_intent_does_not_send(self) -> None:
        result = ag52.agent_iskcon_dispatch(
            "intent",
            "Avisa cambio de clase de yoga del domingo",
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "class_update_draft")
        self.assertFalse(result["send_ready"])
        self.assertIn("fields_needed", result["draft"])

    def test_dispatcher_routes_iskcon_message_to_intent_not_ops(self) -> None:
        result = dispatcher.dispatch_local_agent(
            "iskcon",
            message="prepara mensajes diarios de yoga para WhatsApp",
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["routed_to"], "AG-52")
        self.assertEqual(result["result"]["action"], "yoga_whatsapp_campaign")
        self.assertNotIn("would_create_ops", result["result"])

    def test_fabric_runner_passes_message_to_ag52(self) -> None:
        runner = pool_agent_runners._import_dedicated()["AG-52"]
        result = runner(message="dos mensajes diarios de yoga vaishnava para WhatsApp", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["agent_id"], "AG-52")
        self.assertEqual(result["result_action"], "yoga_whatsapp_campaign")

    def test_mcp_profile_exposes_specific_iskcon_tools(self) -> None:
        profile = mcp_profiles.PROFILES["iskcon_ops"]
        self.assertIn("module_manifest", profile["tools"])
        self.assertIn("module_action", profile["tools"])
        self.assertIn("module_artifact_download", profile["tools"])
        self.assertIn("agent_iskcon_module_manifest", profile["tools"])
        self.assertIn("agent_iskcon_action", profile["tools"])
        self.assertIn("agent_iskcon_artifact_download", profile["tools"])
        self.assertIn("agent_iskcon_sources", profile["tools"])
        self.assertIn("agent_iskcon_yoga_campaign", profile["tools"])
        self.assertIn("agent_iskcon_class_update", profile["tools"])
        for name in (
            "module_manifest",
            "module_action",
            "module_artifact_download",
            "agent_iskcon_module_manifest",
            "agent_iskcon_action",
            "agent_iskcon_artifact_download",
            "agent_iskcon_sources",
            "agent_iskcon_yoga_campaign",
            "agent_iskcon_class_update",
        ):
            self.assertIn(name, tool_catalog.ALL_MCP_TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
