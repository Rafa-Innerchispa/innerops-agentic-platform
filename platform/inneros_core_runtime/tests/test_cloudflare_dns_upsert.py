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


if __name__ == "__main__":
    unittest.main()
