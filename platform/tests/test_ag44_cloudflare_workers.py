import unittest
from unittest.mock import patch

from inneros_core_runtime.agents import ag44_cloud_deployer as ag44


class CloudflareWorkersTests(unittest.TestCase):
    def test_preflight_reports_missing_workers_permission_without_secret(self):
        def fake_request(method, path, *, body=None, creds=None):
            if path.startswith("/zones?"):
                return {"success": True, "result": [{"id": "zone1", "name": "creatorcore.ai"}]}
            if "/workers/scripts" in path:
                raise RuntimeError("cloudflare_api_http_403:permission denied")
            if "/workers/services" in path:
                raise RuntimeError("cloudflare_api_http_403:permission denied")
            if "/workers/routes" in path:
                return {"success": True, "result": []}
            raise AssertionError(path)

        with patch.object(ag44, "_cloudflare_credentials", return_value={"account_id": "acct", "token": "secret", "vault_category": "cloudflare_pcdoctor_ai"}), \
             patch.object(ag44, "_cf_request", side_effect=fake_request), \
             patch.object(ag44, "_audit_cloud_ops"):
            result = ag44.cloudflare_workers_preflight("creatorcore.ai")
        self.assertFalse(result["ok"])
        self.assertFalse(result["permissions_ok"])
        self.assertIn("Account:Workers Scripts:Read/Edit", result["missing_permissions"])
        self.assertNotIn("token': 'secret", repr(result))
        self.assertNotIn("Bearer secret", repr(result))

    def test_worker_deploy_dry_run_builds_safe_request_without_mutation(self):
        source = "export default { async fetch() { return new Response('ok') } };"
        with patch.object(ag44, "cloudflare_workers_preflight", return_value={"ok": True, "permissions_ok": True}), \
             patch.object(ag44, "_audit_cloud_ops"):
            result = ag44.cloudflare_worker_deploy("inneros-webmcp-edge", source_text=source, zone_name="creatorcore.ai", route_pattern="webmcp.creatorcore.ai/edge/attest*", project_id="inneros-webmcp", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertIn("--routes=webmcp.creatorcore.ai/edge/attest*", result["command"])
        self.assertEqual(result["source"]["origin"], "provided_text")

    def test_worker_deploy_requires_approval_for_mutation(self):
        with patch.object(ag44, "cloudflare_workers_preflight", return_value={"ok": True, "permissions_ok": True}), \
             patch.object(ag44, "_audit_cloud_ops"):
            result = ag44.cloudflare_worker_deploy("inneros-webmcp-edge", source_text="export default {};", zone_name="creatorcore.ai", route_pattern="webmcp.creatorcore.ai/edge/attest*", project_id="inneros-webmcp", dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["validation"]["error"], "approval_id_required")
        self.assertFalse(result["executed"])

    def test_worker_route_must_stay_inside_allowlisted_zone(self):
        with self.assertRaises(ValueError):
            ag44._validate_worker_route_pattern("evil.example.com/edge/attest*", "creatorcore.ai")
        with self.assertRaises(ValueError):
            ag44._validate_worker_route_pattern("webmcp.creatorcore.ai/edge/attest*?debug=1", "creatorcore.ai")

    def test_worker_source_rejects_raw_secret_patterns(self):
        result = ag44._load_worker_source(source_text="const token = 'abcdefghijklmnopqrstuvwxyz';")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "raw_secret_pattern_denied")


if __name__ == "__main__":
    unittest.main()
