import unittest

from inneros_core_runtime.agents import ag55_browser_ops_agent as ag55


class AG55BrowserLoopbackTests(unittest.TestCase):
    def test_localhost_8088_matches_status_policy_without_local_preview(self):
        default_allowed = ag55._url_allowed_result("http://localhost:8088/")
        allowed = ag55._url_allowed_result("http://localhost:8088/", local_preview=True)
        self.assertTrue(default_allowed["ok"])
        self.assertEqual(default_allowed["mode"], "loopback_allowlist")
        self.assertTrue(allowed["ok"])
        self.assertEqual(allowed["mode"], "local_preview")

    def test_127_0_0_1_8088_passes_with_local_preview(self):
        result = ag55._url_allowed_result("http://127.0.0.1:8088/", local_preview=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["port"], 8088)

    def test_127_0_0_1_other_port_rejected(self):
        result = ag55._url_allowed_result("http://127.0.0.1:9999/")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "loopback_not_allowlisted")

    def test_metadata_endpoint_rejected(self):
        result = ag55._url_allowed_result("http://169.254.169.254/latest/meta-data")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "private_or_metadata_host_blocked")

    def test_lan_ip_rejected_by_default(self):
        result = ag55._url_allowed_result("http://192.168.1.4:8088/")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "private_or_metadata_host_blocked")

    def test_redirect_target_guard_rejects_non_allowlisted_host(self):
        result = ag55._url_allowed_result("http://not-allowed.invalid/")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "domain_not_allowlisted")


if __name__ == "__main__":
    unittest.main()
