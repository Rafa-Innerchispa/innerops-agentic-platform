import unittest
from unittest.mock import patch
from universal_bootstrap import (
    BOOTSTRAP_VERSION,
    ProbeResult,
    TOPOLOGY,
    enroll_device,
    get_enrolled_device_profile,
    resolve_universal_bootstrap,
)


class TestUniversalBootstrap(unittest.TestCase):
    def test_resolve_lan_tier_when_local(self):
        def mock_prober():
            return [
                ProbeResult("loopback_mcp", "lan", True, 0.5),
                ProbeResult("intel_lan_mcp", "lan", True, 0.2),
                ProbeResult("amd_lan_mcp", "lan", True, 0.3),
                ProbeResult("intel_ts_mcp", "tailscale", True, 0.5),
                ProbeResult("amd_ts_mcp", "tailscale", True, 0.5),
                ProbeResult("cloudflare_mcp_full", "cloudflare_https", True, 100.0, 200),
                ProbeResult("cloudflare_mcp_compact", "cloudflare_https", True, 100.0, 200),
            ]

        res = resolve_universal_bootstrap(custom_prober=mock_prober)
        self.assertEqual(res["tier_selected"], "lan")
        self.assertEqual(res["active_node"], "intel")
        self.assertTrue(res["failover_available"])
        self.assertIn("127.0.0.1", res["endpoints"]["mcp_full"])
        self.assertIsNotNone(res["endpoints"]["mongo_uri"])
        self.assertTrue(res["fresh_session_auto_bootstrap"])

    def test_resolve_tailscale_tier_when_remote_tailnet(self):
        def mock_prober():
            return [
                ProbeResult("loopback_mcp", "lan", False, 100.0, None, "Connection refused"),
                ProbeResult("intel_lan_mcp", "lan", False, 100.0, None, "Timeout"),
                ProbeResult("amd_lan_mcp", "lan", False, 100.0, None, "Timeout"),
                ProbeResult("intel_ts_mcp", "tailscale", True, 25.0),
                ProbeResult("amd_ts_mcp", "tailscale", True, 28.0),
                ProbeResult("cloudflare_mcp_full", "cloudflare_https", True, 150.0, 200),
                ProbeResult("cloudflare_mcp_compact", "cloudflare_https", True, 150.0, 200),
            ]

        res = resolve_universal_bootstrap(custom_prober=mock_prober)
        self.assertEqual(res["tier_selected"], "tailscale")
        self.assertEqual(res["active_node"], "intel")
        self.assertTrue(res["failover_available"])
        self.assertIn(TOPOLOGY["intel"]["ts_ip"], res["endpoints"]["mcp_full"])
        self.assertIn(TOPOLOGY["intel"]["ts_ip"], res["endpoints"]["mongo_uri"])

    def test_resolve_cloudflare_https_when_external_only(self):
        def mock_prober():
            return [
                ProbeResult("loopback_mcp", "lan", False, 100.0, None, "Connection refused"),
                ProbeResult("intel_lan_mcp", "lan", False, 100.0, None, "Timeout"),
                ProbeResult("amd_lan_mcp", "lan", False, 100.0, None, "Timeout"),
                ProbeResult("intel_ts_mcp", "tailscale", False, 100.0, None, "Timeout"),
                ProbeResult("amd_ts_mcp", "tailscale", False, 100.0, None, "Timeout"),
                ProbeResult("cloudflare_mcp_full", "cloudflare_https", True, 80.0, 200),
                ProbeResult("cloudflare_mcp_compact", "cloudflare_https", True, 85.0, 200),
            ]

        res = resolve_universal_bootstrap(custom_prober=mock_prober)
        self.assertEqual(res["tier_selected"], "cloudflare_https")
        self.assertEqual(res["endpoints"]["mcp_full"], "https://mcp.pcdoctor.ai/mcp")
        self.assertEqual(res["endpoints"]["mcp_compact"], "https://mcp-chatgpt.creatorcore.ai/mcp")
        self.assertIsNone(res["endpoints"]["mongo_uri"])

    def test_intel_to_amd_failover(self):
        def mock_prober():
            return [
                ProbeResult("loopback_mcp", "lan", False, 100.0, None, "Refused"),
                ProbeResult("intel_lan_mcp", "lan", False, 100.0, None, "Down"),
                ProbeResult("amd_lan_mcp", "lan", True, 0.4),
                ProbeResult("intel_ts_mcp", "tailscale", False, 100.0, None, "Down"),
                ProbeResult("amd_ts_mcp", "tailscale", True, 1.2),
                ProbeResult("cloudflare_mcp_full", "cloudflare_https", True, 120.0, 200),
                ProbeResult("cloudflare_mcp_compact", "cloudflare_https", True, 120.0, 200),
            ]

        res = resolve_universal_bootstrap(custom_prober=mock_prober)
        self.assertEqual(res["tier_selected"], "lan")
        self.assertEqual(res["active_node"], "amd")
        self.assertIn(TOPOLOGY["amd"]["lan_ip"], res["endpoints"]["mcp_full"])

    def test_force_tier_override(self):
        def mock_prober():
            return [
                ProbeResult("loopback_mcp", "lan", True, 0.5),
                ProbeResult("intel_lan_mcp", "lan", True, 0.2),
                ProbeResult("amd_lan_mcp", "lan", True, 0.3),
                ProbeResult("intel_ts_mcp", "tailscale", True, 0.5),
                ProbeResult("amd_ts_mcp", "tailscale", True, 0.5),
                ProbeResult("cloudflare_mcp_full", "cloudflare_https", True, 100.0, 200),
                ProbeResult("cloudflare_mcp_compact", "cloudflare_https", True, 100.0, 200),
            ]

        res = resolve_universal_bootstrap(force_tier="cloudflare_https", custom_prober=mock_prober)
        self.assertEqual(res["tier_selected"], "cloudflare_https")
        self.assertEqual(res["endpoints"]["mcp_full"], "https://mcp.pcdoctor.ai/mcp")
        self.assertIsNone(res["endpoints"]["mongo_uri"])

    def test_device_enrollment(self):
        profile = enroll_device(device_name="test-laptop-enrollment", preferred_tier="tailscale")
        self.assertTrue(profile["enrolled"])
        self.assertEqual(profile["device_name"], "test-laptop-enrollment")
        self.assertEqual(profile["preferred_tier"], "tailscale")

        read_back = get_enrolled_device_profile()
        self.assertTrue(read_back["enrolled"])
        self.assertEqual(read_back["device_name"], "test-laptop-enrollment")


if __name__ == "__main__":
    unittest.main()
