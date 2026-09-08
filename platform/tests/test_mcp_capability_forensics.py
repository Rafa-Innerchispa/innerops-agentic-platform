from pathlib import Path
import ast
import sys
import unittest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import mcp_capability_forensics
from raphiia_openai.mcp_catalog import tool_catalog


CATALOG_A = '''
MCP_VERSION = "1.0"
ALL_MCP_TOOL_NAMES = ["alpha", "beta"]
'''
SERVER_A = '''
def alpha():
    return {}
def beta():
    return {}
'''
CATALOG_B = '''
MCP_VERSION = "1.1"
ALL_MCP_TOOL_NAMES = ["alpha", "gamma"]
'''
SERVER_B = '''
def alpha():
    return {}
'''


class McpCapabilityForensicsTests(unittest.TestCase):
    def test_snapshot_marks_declared_tool_without_backend(self):
        snap = mcp_capability_forensics.snapshot_from_sources(
            label="candidate",
            catalog_source=CATALOG_B,
            server_source=SERVER_B,
        )
        self.assertEqual(snap["tool_count"], 2)
        self.assertEqual(snap["backend_unavailable"], ["gamma"])

    def test_release_gate_blocks_unapproved_tool_removal_and_backend_regression(self):
        previous = mcp_capability_forensics.snapshot_from_sources(
            label="previous",
            catalog_source=CATALOG_A,
            server_source=SERVER_A,
        )
        current = mcp_capability_forensics.snapshot_from_sources(
            label="candidate",
            catalog_source=CATALOG_B,
            server_source=SERVER_B,
        )
        result = mcp_capability_forensics.compare_snapshots(previous, current)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["removed_tools"], ["beta"])
        self.assertEqual(
            [issue["code"] for issue in result["issues"]],
            ["CAPABILITY_REMOVAL_REQUIRES_OWNER_APPROVAL", "CATALOG_BACKEND_REGRESSION"],
        )

    def test_owner_approval_can_clear_removal_but_not_missing_backend(self):
        previous = mcp_capability_forensics.snapshot_from_sources(
            label="previous",
            catalog_source=CATALOG_A,
            server_source=SERVER_A,
        )
        current = mcp_capability_forensics.snapshot_from_sources(
            label="candidate",
            catalog_source=CATALOG_B,
            server_source=SERVER_B,
        )
        result = mcp_capability_forensics.compare_snapshots(
            previous,
            current,
            owner_approved_removals=["beta"],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["approved_removed_tools"], ["beta"])
        self.assertEqual([issue["code"] for issue in result["issues"]], ["CATALOG_BACKEND_REGRESSION"])

    def test_owner_approval_passes_when_backends_are_available(self):
        previous = mcp_capability_forensics.snapshot_from_sources(
            label="previous",
            catalog_source=CATALOG_A,
            server_source=SERVER_A,
        )
        current = mcp_capability_forensics.snapshot_from_sources(
            label="candidate",
            catalog_source=CATALOG_B,
            server_source=SERVER_B + "\ndef gamma():\n    return {}\n",
        )
        result = mcp_capability_forensics.compare_snapshots(
            previous,
            current,
            owner_approved_removals=["beta"],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "PASS")

    def test_catalog_exposes_forensic_tools_and_server_declares_wrappers(self):
        expected = {
            "mcp_capability_snapshot",
            "mcp_capability_diff",
            "mcp_capability_release_gate",
        }
        self.assertTrue(expected.issubset(set(tool_catalog.ALL_MCP_TOOL_NAMES)))
        source = (PLATFORM_ROOT / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertTrue(expected.issubset(functions))
        for name in expected:
            meta = tool_catalog.describe_tool(name)
            self.assertTrue(meta["ok"])
            self.assertEqual(meta["required_scopes"], ["ralfia:read"])
            self.assertEqual(meta["risk_level"], "low")

    def test_current_release_gate_is_read_only_and_machine_readable(self):
        result = mcp_capability_forensics.release_gate()
        self.assertIn(result["status"], {"PASS", "BLOCKED"})
        self.assertEqual(result["gate"], "mcp_capability_release_gate")
        self.assertIn("retirement_flow", result["policy"])

    def test_every_catalog_tool_has_describable_metadata(self):
        failures = []
        for name in tool_catalog.ALL_MCP_TOOL_NAMES:
            meta = tool_catalog.describe_tool(name)
            if not meta.get("ok"):
                failures.append((name, meta))
                continue
            for key in ("description", "input_schema", "output_schema", "required_scopes", "example_payload", "risk_level", "writes_to", "reads_from"):
                if key not in meta:
                    failures.append((name, key))
        self.assertEqual(failures, [])

    def test_restored_historical_capabilities_have_live_wrappers(self):
        restored = {
            "agent_iskcon_yoga_campaign",
            "agent_iskcon_class_update",
            "get_disk_steward_status",
            "identify_agent_session",
            "judge_workflow_start",
            "judge_workflow_execute",
            "judge_trace_current",
            "judge_trace_kpis",
            "save_self_heal_baseline",
            "inneros_ingest_drop_status",
        }
        source = (PLATFORM_ROOT / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertTrue(restored.issubset(functions))
        self.assertTrue(restored.issubset(set(tool_catalog.ALL_MCP_TOOL_NAMES)))
        snapshot = mcp_capability_forensics.current_snapshot()
        self.assertFalse(restored.intersection(set(snapshot["backend_unavailable"])))

    def test_all_baseline_removed_capabilities_are_either_restored_or_gate_visible(self):
        baseline_removed = {
            "agent_iskcon_action",
            "agent_iskcon_artifact_download",
            "agent_iskcon_module_manifest",
            "disk_steward_cleanup_verified",
            "disk_steward_execute_migration",
            "disk_steward_inventory",
            "disk_steward_plan_migration",
            "disk_steward_update_backup_policy",
            "disk_steward_verify_migration",
            "editorial_image_providers",
            "inneros_dual_deployment_drill",
            "inneros_dual_deployment_status",
            "inneros_dual_queue_operation",
            "inneros_dual_reconcile_operations",
            "module_action",
            "module_artifact_download",
            "module_manifest",
        }
        source = (PLATFORM_ROOT / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertTrue(baseline_removed.issubset(functions))
        self.assertTrue(baseline_removed.issubset(set(tool_catalog.ALL_MCP_TOOL_NAMES)))
        snapshot = mcp_capability_forensics.current_snapshot()
        self.assertFalse(baseline_removed.intersection(set(snapshot["backend_unavailable"])))


if __name__ == "__main__":
    unittest.main()
