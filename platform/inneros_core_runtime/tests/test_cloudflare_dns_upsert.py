import unittest
from unittest.mock import patch

from inneros_core_runtime.agents import ag44_cloud_deployer as ag44


class CloudflareDnsUpsertTests(unittest.TestCase):
    def test_mx_record_supported_with_priority_in_dry_run(self):
        with patch.object(ag44, "_cloudflare_credentials", return_value={"account_id": "acct", "api_token": "token"}),             patch.object(ag44, "_get_zone", return_value={"id": "zone", "name": "torresdelrio.net"}):
            result = ag44.cloudflare_dns_upsert(
                "torresdelrio.net",
                "MX",
                "mail.torresdelrio.net",
                priority=10,
                proxied=True,
                ttl=3600,
                zone_name="torresdelrio.net",
                dry_run=True,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["type"], "MX")
        self.assertEqual(result["record"]["priority"], 10)
        self.assertFalse(result["record"]["proxied"])

    def test_provider_status_finds_gcloud_in_home_local_bin(self):
        with patch.object(ag44.shutil, "which", return_value=None), \
            patch.object(ag44.Path, "exists", return_value=True), \
            patch.object(ag44.os, "access", return_value=True), \
            patch.object(ag44, "_gcp_readiness", return_value={"auth": {"ok": True}}):
            result = ag44.cloud_provider_status("gcp")
        self.assertTrue(result["cli_available"])
        self.assertEqual(result["cli_path"], "/home/rlopez/.local/bin/gcloud")


    def test_cloud_run_domain_mapping_status_uses_domain_flag(self):
        with patch.object(ag44, "_gcp_read_json", return_value={"ok": False, "error": "not_found"}) as read_json:
            ag44.gcp_cloud_run_domain_mapping_status("innerops-agentic-platform", "inneros.pcdoctor.ai", region="us-central1")
        argv = read_json.call_args.args[1]
        self.assertIn("--domain", argv)
        self.assertIn("inneros.pcdoctor.ai", argv)

    def test_cloud_run_domain_mapping_create_is_dry_run_gated(self):
        with patch.object(ag44, "_gcp_apply_validation", return_value={"ok": True, "dry_run": True, "project_id": "innerops-agentic-platform"}):
            result = ag44.gcp_cloud_run_domain_mapping_create(
                "innerops-agentic-platform",
                "inneros",
                "inneros.pcdoctor.ai",
                region="us-central1",
                dry_run=True,
            )
        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(result["command"][:5], ["gcloud", "beta", "run", "domain-mappings", "create"])
        self.assertIn("inneros.pcdoctor.ai", result["command"])

    def test_cloud_run_domain_mapping_rejects_unowned_domain(self):
        with self.assertRaises(ValueError):
            ag44.gcp_cloud_run_domain_mapping_status("innerops-agentic-platform", "not-owned.example.com", region="us-central1")



if __name__ == "__main__":
    unittest.main()
