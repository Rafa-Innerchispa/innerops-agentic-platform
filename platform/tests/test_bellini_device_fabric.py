"""
Carril B: Unit & Integration Tests for Bellini Device Fabric & Failure Domains
Correlation ID: bellini-capability-gateway-20260930 / Carril B
"""

import unittest
from inneros_core_runtime.device_fabric import device_fabric_get, device_fabric_inventory
from inneros_core_runtime.bellini_failure_domains import (
    get_failure_domains,
    classify_device_health,
    OP_STATE_ONLINE,
    OP_STATE_DEGRADED,
    OP_STATE_OFFLINE
)
from inneros_core_runtime.capability_gateway import capability_invoke


class TestBelliniDeviceFabric(unittest.TestCase):

    def test_01_resolve_gcc6010_in_device_fabric(self):
        """Verify GCC6010 (192.168.3.1) resolves canonically in Device Fabric."""
        res = device_fabric_get("192.168.3.1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["kind"], "device")
        dev = res["device"]
        
        # Identity
        self.assertEqual(dev["model"], "GCC6010")
        self.assertEqual(dev["ip"], "192.168.3.1")
        self.assertEqual(dev["mac"], "00:0B:82:F1:22:A1")
        self.assertEqual(dev["firmware"], "1.0.7.71")
        self.assertEqual(dev["role"], "CORE_ROUTER")
        self.assertEqual(dev["operational_state"], OP_STATE_ONLINE)
        
        # Telemetry & DHCP
        self.assertEqual(dev["uptime"], "55d 04h")
        self.assertEqual(dev["dhcp"]["subnet"], "192.168.3.0/24")
        self.assertEqual(dev["dhcp"]["pool_start"], "192.168.3.10")
        self.assertEqual(dev["dhcp"]["pool_end"], "192.168.3.250")
        self.assertEqual(dev["dhcp"]["lease_time_seconds"], 86400)
        
        # Interfaces & SFP Ownership
        ifaces = dev["interfaces"]
        lan1 = next((i for i in ifaces if i["name"] == "LAN1"), None)
        self.assertIsNotNone(lan1)
        self.assertEqual(lan1["connected_to"], "SW_CONSOLA")
        
        sfp1 = next((i for i in ifaces if i["name"] == "SFP1"), None)
        self.assertIsNotNone(sfp1)
        self.assertEqual(sfp1["owner"], "GCC6010")

    def test_02_resolve_gcc6010_by_model_alias(self):
        """Verify GCC6010 resolves by model alias 'GCC6010'."""
        res = device_fabric_get("GCC6010")
        self.assertTrue(res["ok"])
        self.assertEqual(res["device"]["ip"], "192.168.3.1")

    def test_03_failure_domains_structure_and_health(self):
        """Verify failure domains categorize core, switches, PoE, and CCTV domains."""
        fd_res = get_failure_domains("bellini-i-ii")
        self.assertTrue(fd_res["ok"])
        domains = fd_res["failure_domains"]
        domain_ids = [d["id"] for d in domains]
        
        self.assertIn("FD-CORE-GCC", domain_ids)
        self.assertIn("FD-SW-CONSOLA", domain_ids)
        self.assertIn("FD-POE-HIKVISION-185", domain_ids)
        self.assertIn("FD-SW-T1-P0", domain_ids)
        self.assertIn("FD-SW-T2-P0", domain_ids)
        self.assertIn("FD-CCTV-DAHUA", domain_ids)
        
        # Status checks
        core_domain = next(d for d in domains if d["id"] == "FD-CORE-GCC")
        self.assertEqual(core_domain["status"], OP_STATE_ONLINE)
        
        poe_domain = next(d for d in domains if d["id"] == "FD-POE-HIKVISION-185")
        self.assertEqual(poe_domain["status"], OP_STATE_OFFLINE)

    def test_04_operational_health_state_separation(self):
        """Verify clear separation between ONLINE, DEGRADED, and OFFLINE operational states."""
        # Core is ONLINE
        h_gcc = classify_device_health("192.168.3.1")
        self.assertEqual(h_gcc["operational_state"], OP_STATE_ONLINE)
        self.assertEqual(h_gcc["telemetry_state"], "MEASURED")
        
        # Switch .185 is OFFLINE
        h_sw = classify_device_health("192.168.3.185")
        self.assertEqual(h_sw["operational_state"], OP_STATE_OFFLINE)
        self.assertEqual(h_sw["telemetry_state"], "UNREACHABLE")
        
        # Cascading AP .207 is DEGRADED
        h_ap = classify_device_health("192.168.3.207")
        self.assertEqual(h_ap["operational_state"], OP_STATE_DEGRADED)
        self.assertEqual(h_ap["failure_domain"], "FD-POE-HIKVISION-185")

    def test_05_capability_invoke_network_query_real_data(self):
        """Verify network.device.query.v1 returns real telemetry from Device Fabric."""
        params = {
            "tenant": "bellini",
            "site": "bellini-i-ii",
            "mode": "read_only",
            "device_ref": "192.168.3.1",
            "sections": ["interfaces", "dhcp", "health", "inventory"]
        }
        res = capability_invoke("network.device.query.v1", params)
        self.assertTrue(res["ok"])
        data = res["result"]["data"]
        
        self.assertEqual(data["health"]["uptime"], "55d 04h")
        self.assertEqual(data["dhcp"]["subnet"], "192.168.3.0/24")
        self.assertEqual(data["dhcp"]["lease_time_seconds"], 86400)


if __name__ == "__main__":
    unittest.main()
