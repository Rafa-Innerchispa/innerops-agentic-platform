import unittest
from unittest.mock import patch

from raphiia_openai.agents import ag41_peer_ops_executor
from raphiia_openai.notifications import whatsapp_service_ops


class PeerRoutingTests(unittest.TestCase):
    def test_intel_and_primary_route_to_intel_host(self):
        self.assertEqual(whatsapp_service_ops.normalize_node("intel"), "primary")
        self.assertEqual(whatsapp_service_ops.normalize_node("primary"), "primary")
        self.assertEqual(whatsapp_service_ops.NODE_HOSTS[whatsapp_service_ops.normalize_node("intel")], "192.168.1.4")
        self.assertEqual(whatsapp_service_ops.NODE_HOSTS[whatsapp_service_ops.normalize_node("primary")], "192.168.1.4")

    def test_amd_routes_to_amd_host(self):
        self.assertEqual(whatsapp_service_ops.normalize_node("amd"), "amd")
        self.assertEqual(whatsapp_service_ops.NODE_HOSTS[whatsapp_service_ops.normalize_node("amd")], "192.168.1.5")

    def test_peer_registry_contract(self):
        nodes = ag41_peer_ops_executor.list_peer_ops_services()["nodes"]
        self.assertEqual(nodes["primary"]["host"], "192.168.1.4")
        self.assertEqual(nodes["intel"]["host"], "192.168.1.4")
        self.assertEqual(nodes["amd"]["host"], "192.168.1.5")
        self.assertEqual(nodes["desktop-t2jle71"]["host"], "100.103.151.40")
        self.assertEqual(nodes["desktop-t2jle71"]["lan_host"], "192.168.3.236")
        self.assertEqual(nodes["desktop-t2jle71"]["authorized_subnets"], ["192.168.3.0/24"])
        self.assertEqual(nodes["desktop-t2jle71"]["gateway"], "192.168.3.1")
        self.assertEqual(nodes["desktop-t2jle71"]["transport"], "tailscale_subnet")

    def test_bellini_peer_routes_to_tailscale_host(self):
        self.assertEqual(whatsapp_service_ops.normalize_node("desktop-t2jle71"), "desktop-t2jle71")
        self.assertEqual(whatsapp_service_ops.normalize_node("bellini-lobby"), "desktop-t2jle71")
        self.assertEqual(whatsapp_service_ops.normalize_node("100.103.151.40"), "desktop-t2jle71")
        self.assertEqual(whatsapp_service_ops.normalize_node("192.168.3.236"), "desktop-t2jle71")
        node = whatsapp_service_ops.normalize_node("desktop-t2jle71")
        self.assertEqual(whatsapp_service_ops.NODE_HOSTS[node], "100.103.151.40")

    def test_bellini_route_check_uses_tailscale_subnet_transport(self):
        probe = {
            "ok": True,
            "node": "desktop-t2jle71",
            "transport": "tailscale_subnet",
            "host": "100.103.151.40",
            "gateway": "192.168.3.1",
            "lan_host": "192.168.3.236",
            "authorized_subnets": ["192.168.3.0/24"],
            "fallback": "denied",
        }
        with patch.object(ag41_peer_ops_executor, "_tailscale_subnet_route_check", return_value=dict(probe)):
            result = ag41_peer_ops_executor.peer_route_check("desktop-t2jle71")
        self.assertTrue(result["ok"])
        self.assertEqual(result["node"], "desktop-t2jle71")
        self.assertEqual(result["transport"], "tailscale_subnet")
        self.assertEqual(result["host"], "100.103.151.40")
        self.assertNotEqual(result["node"], "primary")
        self.assertEqual(result["fallback"], "denied")

    def test_unknown_peer_fails_closed(self):
        with self.assertRaises(ValueError):
            whatsapp_service_ops.normalize_node("does-not-exist")
        result = ag41_peer_ops_executor.peer_route_check("does-not-exist")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_peer_node")
        self.assertEqual(result["fallback"], "denied")
        self.assertEqual(result["node"], "does-not-exist")


if __name__ == "__main__":
    unittest.main()
