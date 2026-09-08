"""Regression tests for AG-52 ISKCON intent-aware operations."""
from __future__ import annotations

import unittest

from inneros_core_runtime.agents import ag49_local_dispatcher as dispatcher
from inneros_core_runtime.agents import ag52_iskcon_ops_agent as ag52
from inneros_core_runtime.agents import pool_agent_runners
from inneros_core_runtime import mcp_profiles
from inneros_core_runtime.mcp_catalog import tool_catalog


class AG52IskconOpsTests(unittest.TestCase):
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
        self.assertIn("agent_iskcon_sources", profile["tools"])
        self.assertIn("agent_iskcon_yoga_campaign", profile["tools"])
        self.assertIn("agent_iskcon_class_update", profile["tools"])
        for name in ("agent_iskcon_sources", "agent_iskcon_yoga_campaign", "agent_iskcon_class_update"):
            self.assertIn(name, tool_catalog.ALL_MCP_TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
