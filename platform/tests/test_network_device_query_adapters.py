"""
Unit & Integration Tests for Network Device Query Adapters
Correlation ID: bellini-capability-gateway-20260930
"""

import unittest
from inneros_core_runtime.capability_gateway import (
    capability_search,
    capability_describe,
    capability_invoke,
    capability_execution
)
from inneros_core_runtime.adapters.base_adapter import (
    STATE_MEASURED,
    STATE_CONFIGURED,
    STATE_OBSERVED,
    STATE_UNSUPPORTED,
    STATE_UNREACHABLE
)
from inneros_core_runtime.bellini_incident_correlator import BelliniIncidentCorrelator


class TestNetworkDeviceQueryAdapters(unittest.TestCase):

    def test_01_gcc6010_e2e_query(self):
        """Test GCC6010 (.1) read-only query for all major sections."""
        params = {
            "tenant": "bellini",
            "site": "bellini-i-ii",
            "mode": "read_only",
            "device_ref": "192.168.3.1",
            "sections": ["interfaces", "arp", "dhcp", "vlans", "routes", "logs", "events", "firmware", "health", "inventory"]
        }
        res = capability_invoke("network.device.query.v1", params)
        self.assertTrue(res["ok"])
        data = res["result"]["data"]
        
        # Check interfaces
        self.assertIn("interfaces", data)
        self.assertTrue(any(iface["name"] == "LAN1" for iface in data["interfaces"]))
        self.assertTrue(any(iface["name"] == "SFP1" for iface in data["interfaces"]))
        
        # Check DHCP
        self.assertIn("dhcp", data)
        self.assertEqual(data["dhcp"]["subnet"], "192.168.3.0/24")
        self.assertEqual(data["dhcp"]["lease_time_seconds"], 86400)
        
        # Check Firmware & Health
        self.assertEqual(data["firmware"]["current_version"], "1.0.7.71")
        self.assertEqual(data["health"]["status"], "ONLINE")
        self.assertEqual(data["health"]["uptime"], "55d 04h")

    def test_02_ucm_integrated_query(self):
        """Test integrated UCM (.2) for PBX, SIP clients, and health."""
        params = {
            "tenant": "bellini",
            "site": "bellini-i-ii",
            "mode": "read_only",
            "device_ref": "192.168.3.2",
            "sections": ["inventory", "health", "clients", "events", "logs", "firmware"]
        }
        res = capability_invoke("network.device.query.v1", params)
        self.assertTrue(res["ok"])
        data = res["result"]["data"]
        
        self.assertEqual(data["inventory"]["role"], "VoIP PBX / SIP Server")
        self.assertEqual(data["clients"]["sip_extensions_registered"], 12)
        self.assertEqual(data["firmware"]["current_version"], "1.0.21.14")

    def test_03_gwn_cloud_ap_fleet(self):
        """Test GWN Cloud adapter for AP inventory, clients, SSIDs, and channels."""
        params = {
            "tenant": "bellini",
            "site": "bellini-i-ii",
            "mode": "read_only",
            "device_ref": "gwn_cloud",
            "provider_hint": "grandstream_gwn",
            "sections": ["inventory", "clients", "firmware", "events", "health", "vlans", "channels"]
        }
        res = capability_invoke("network.device.query.v1", params)
        self.assertTrue(res["ok"])
        data = res["result"]["data"]
        
        self.assertEqual(data["inventory"]["total_aps"], 7)
        self.assertEqual(data["clients"]["total_wireless_clients"], 68)
        self.assertTrue(any(s["ssid"] == "Bellini-Residentes" for s in data["vlans"]["ssid_vlan_mappings"]))

    def test_04_hikvision_unreachable_handling(self):
        """Test Hikvision (.185) returns UNREACHABLE without throwing adapter errors."""
        params = {
            "tenant": "bellini",
            "site": "bellini-i-ii",
            "mode": "read_only",
            "device_ref": "192.168.3.185",
            "sections": ["interfaces", "mac_table", "lldp", "poe", "events", "firmware"]
        }
        res = capability_invoke("network.device.query.v1", params)
        self.assertTrue(res["ok"])
        section_status = res["result"]["section_status"]
        self.assertEqual(section_status["interfaces"], STATE_UNREACHABLE)
        self.assertEqual(section_status["poe"], STATE_UNREACHABLE)

    def test_05_dahua_nvr_query(self):
        """Test Dahua NVR (.100) for channels, storage, and health."""
        params = {
            "tenant": "bellini",
            "site": "bellini-i-ii",
            "mode": "read_only",
            "device_ref": "192.168.3.100",
            "sections": ["inventory", "health", "channels", "storage", "firmware", "events"]
        }
        res = capability_invoke("network.device.query.v1", params)
        self.assertTrue(res["ok"])
        data = res["result"]["data"]
        
        self.assertEqual(data["channels"]["total_active_channels"], 14)
        self.assertEqual(len(data["storage"]["hdds"]), 2)
        self.assertEqual(data["health"]["recording_status"], "NORMAL")

    def test_06_mutation_guard(self):
        """Verify that mode != 'read_only' is rejected."""
        params = {
            "tenant": "bellini",
            "site": "bellini-i-ii",
            "mode": "write",
            "device_ref": "192.168.3.1",
            "sections": ["interfaces"]
        }
        res = capability_invoke("network.device.query.v1", params)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "MUTATION_FORBIDDEN_IN_READ_ONLY_MODE")


class TestBelliniIncidentObservability(unittest.TestCase):

    def test_07_multiple_ap_outage_correlation(self):
        """Test incident correlation across .185, .207, .213, .220, .232, .234."""
        correlator = BelliniIncidentCorrelator()
        findings = correlator.correlate_incident("MULTIPLE_AP_OUTAGE")
        
        self.assertIn("192.168.3.185", findings["unreachable_devices"])
        self.assertIn("192.168.3.207", findings["affected_aps"])
        self.assertIn("192.168.3.188", findings["unaffected_aps"]) # .188 is on separate switch
        self.assertTrue(findings["poe_event_detected"])
        self.assertEqual(findings["evidence_confidence"], "HIGH_CONFIDENCE_CORRELATION")


if __name__ == "__main__":
    unittest.main()
