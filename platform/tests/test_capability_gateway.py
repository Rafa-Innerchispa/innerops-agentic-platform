"""
Unit tests for Governed Capability Gateway
Correlation ID: bellini-capability-gateway-20260930
"""

import unittest
from inneros_core_runtime.capability_gateway import (
    register_capability,
    capability_search,
    capability_describe,
    capability_invoke,
    capability_execution,
    NETWORK_DEVICE_QUERY_MANIFEST
)

class TestCapabilityGateway(unittest.TestCase):

    def test_capability_search(self):
        res = capability_search(query="network")
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(len(res["capabilities"]), 1)
        self.assertEqual(res["capabilities"][0]["capability_id"], "network.device.query.v1")

    def test_capability_describe(self):
        res = capability_describe("network.device.query.v1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["capability"]["title"], "Network Device Unified Query Capability")
        self.assertEqual(res["capability"]["mode"], "read_only")

    def test_capability_invoke_read_only(self):
        res = capability_invoke(
            capability_id="network.device.query.v1",
            parameters={"tenant": "bellini", "device_ref": "192.168.3.1", "sections": ["health", "inventory"]},
            idempotency_key="test-idem-pytest-01"
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "COMPLETED")
        self.assertIn("health", res["result"]["data"])
        self.assertIn("inventory", res["result"]["data"])

    def test_capability_invoke_mutation_guard(self):
        # Register mutation capability
        mut_manifest = {
            "capability_id": "test.mutation.sample.v1",
            "version": "1.0.0",
            "title": "Sample Mutation Capability",
            "domain": "test",
            "mode": "mutation",
            "risk_class": "high"
        }
        register_capability(mut_manifest, lambda p, c: {"mutated": True})

        # When mode != read_only or context enforce_read_only is active, it must fail-closed
        res = capability_invoke(
            capability_id="test.mutation.sample.v1",
            parameters={"mode": "write"},
            context={"enforce_read_only": True}
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "MUTATION_FORBIDDEN_IN_READ_ONLY_MODE")

    def test_capability_execution(self):
        res = capability_invoke(
            capability_id="network.device.query.v1",
            parameters={"tenant": "bellini", "device_ref": "192.168.3.1", "sections": ["vlans"]}
        )
        exec_id = res["execution_id"]
        status_res = capability_execution(execution_id=exec_id, action="status")
        self.assertTrue(status_res["ok"])
        self.assertEqual(status_res["execution"]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
