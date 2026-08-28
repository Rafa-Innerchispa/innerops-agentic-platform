from pathlib import Path
import ast
import sys
import unittest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import mcp_profiles
from raphiia_openai.mcp_catalog import tool_catalog
from raphiia_openai import tool_catalog as legacy_tool_catalog

A2A_TOOLS = {
    "a2a_status",
    "a2a_agent_cards",
    "a2a_dispatch",
    "a2a_task_status",
}


class A2AMcpSurfaceTests(unittest.TestCase):
    def test_mcp_server_declares_all_a2a_tools(self):
        source = (PLATFORM_ROOT / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertTrue(A2A_TOOLS.issubset(functions), sorted(A2A_TOOLS - functions))

    def test_catalog_contains_all_a2a_tools(self):
        self.assertTrue(A2A_TOOLS.issubset(set(tool_catalog.ALL_MCP_TOOL_NAMES)))

    def test_ide_bridge_tools_are_in_canonical_and_legacy_catalogs(self):
        wanted = {
            "ide_task_bridge_status",
            "ide_dispatch_task",
            "ide_task_status",
            "ide_claim_task",
            "ide_mark_task_running",
            "ide_complete_task",
        }
        self.assertTrue(wanted.issubset(set(tool_catalog.ALL_MCP_TOOL_NAMES)))
        self.assertTrue(wanted.issubset(set(legacy_tool_catalog.ALL_MCP_TOOL_NAMES)))
        for name in wanted:
            self.assertIn(name, tool_catalog.TOOL_DEFINITIONS)
            self.assertIn(name, legacy_tool_catalog.TOOL_DEFINITIONS)

    def test_a2a_profile_is_complete_and_coordination_can_use_it(self):
        profile = mcp_profiles.PROFILES["a2a"]
        self.assertEqual(set(profile["tools"]), A2A_TOOLS)
        coordination = set(mcp_profiles.PROFILES["coordination"]["tools"])
        self.assertTrue(A2A_TOOLS.issubset(coordination))

    def test_a2a_profiles_have_no_contract_errors(self):
        result = mcp_profiles.validate_profiles()
        a2a_errors = [
            error
            for error in result["errors"]
            if error.get("profile") in {"a2a", "coordination"}
        ]
        self.assertEqual(a2a_errors, [])

    def test_dispatch_requires_agent_scope(self):
        meta = tool_catalog.describe_tool("a2a_dispatch")
        self.assertTrue(meta["ok"])
        self.assertEqual(meta["required_scopes"], ["ralfia:agents"])
        self.assertEqual(meta["risk_level"], "medium")

    def test_all_profiles_satisfy_contract(self):
        result = mcp_profiles.validate_profiles()
        self.assertTrue(result["ok"], result["errors"])

    def test_small_model_profiles_stay_compact(self):
        home = mcp_profiles.PROFILES["home"]
        daily = mcp_profiles.PROFILES["daily_companion"]

        self.assertLessEqual(len(home["tools"]), home["max_tools"])
        self.assertNotIn("ha_batch_rename", home["tools"])
        self.assertNotIn("ha_rename_device", home["tools"])
        self.assertNotIn("ha_rename_entity_name", home["tools"])

        self.assertLessEqual(len(daily["tools"]), daily["max_tools"])
        self.assertNotIn("local_exec_prepare_repo", daily["tools"])
        self.assertNotIn("local_exec_inspect_repo", daily["tools"])
        self.assertNotIn("local_exec_inspect_remotes", daily["tools"])

    def test_operator_profiles_fit_declared_limits(self):
        for profile_name in {
            "owner_dev",
            "local_self_repair",
            "cloud_ops",
            "local_fleet",
            "local_fleet_full",
        }:
            with self.subTest(profile=profile_name):
                profile = mcp_profiles.PROFILES[profile_name]
                self.assertLessEqual(len(profile["tools"]), profile["max_tools"])


if __name__ == "__main__":
    unittest.main()
