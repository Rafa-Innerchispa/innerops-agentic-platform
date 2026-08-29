"""Tests for unified InnerOS agent fabric."""
from __future__ import annotations

import unittest

from inneros_core_runtime import ide_task_bridge, inneros_agent_fabric


class InnerosAgentFabricTests(unittest.TestCase):
    def test_fabric_status_layers(self) -> None:
        status = inneros_agent_fabric.fabric_status()
        self.assertTrue(status["ok"])
        layers = status["layers"]
        self.assertIn("mcp_inbox", layers)
        self.assertIn("ide_task_bridge", layers)
        self.assertIn("acp", layers)

    def test_harmonized_dispatch_wires_acp_and_kpi(self) -> None:
        store: ide_task_bridge.DispatchStore = {}
        result = inneros_agent_fabric.harmonized_dispatch(
            title="T",
            body="B",
            target="cursor",
            correlation_id="fabric-test",
            dry_run=True,
            store=store,
        )
        self.assertTrue(result["ok"])
        self.assertIn("acp_correlation", result)
        self.assertIn("kpi", result)
        self.assertFalse(result["dispatch"]["execution_projection"]["running"])


if __name__ == "__main__":
    unittest.main()
