"""Offline contract tests for the read-only dual-node P0 audit."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_p0_dual_node.py"

spec = importlib.util.spec_from_file_location("audit_p0_dual_node", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DualNodeParityP0Tests(unittest.TestCase):
    def test_critical_files_cover_coordination_auth_and_dual_node_runtime(self):
        required = {
            "platform/inneros_core_runtime/mcp_server.py",
            "platform/inneros_core_runtime/mcp_profiles.py",
            "platform/inneros_core_runtime/mcp_fleet.py",
            "platform/inneros_core_runtime/oauth_metadata.py",
            "platform/inneros_core_runtime/durable_coordination_spine.py",
            "platform/inneros_core_runtime/temporal_worker.py",
            "platform/inneros_core_runtime/agent_identity.py",
            "platform/inneros_core_runtime/memory/agent_messages.py",
        }
        self.assertTrue(required.issubset(set(module.CRITICAL_FILES)))

    def test_same_nonempty_fails_closed_on_missing_values(self):
        self.assertFalse(module.same_nonempty(None, None))
        self.assertFalse(module.same_nonempty("abc", None))
        self.assertTrue(module.same_nonempty("abc", "abc"))
        self.assertFalse(module.same_nonempty("abc", "def"))

    def test_public_endpoint_contract_is_canonical_small_router(self):
        self.assertEqual(module.PUBLIC_MCP_SMALL, "https://mcp.pcdoctor.ai/router/mcp")
        self.assertEqual(
            module.OAUTH_METADATA_URL,
            "https://mcp.pcdoctor.ai/router/mcp/.well-known/oauth-protected-resource",
        )


if __name__ == "__main__":
    unittest.main()
