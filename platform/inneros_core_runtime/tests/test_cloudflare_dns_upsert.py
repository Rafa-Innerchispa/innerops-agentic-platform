import unittest
from unittest.mock import patch

from inneros_core_runtime.agents import ag44_cloud_deployer as ag44
from inneros_core_runtime import cloudflare_ops


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


    def test_tunnel_ingress_upsert_delegates_to_canonical_helper(self):
        with (
            patch.object(
                cloudflare_ops,
                "ensure_tunnel_ingress",
                return_value={"ok": True, "action": "inserted"},
            ) as ensure,
            patch.object(ag44, "_audit", return_value=None),
        ):
            result = ag44.cloudflare_tunnel_ingress_upsert(
                "infralens.creatorcore.ai",
                "http://192.168.1.5:18501",
                dry_run=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["hostname"], "infralens.creatorcore.ai")
        self.assertEqual(result["service"], "http://192.168.1.5:18501")
        ensure.assert_called_once_with(
            "infralens.creatorcore.ai",
            "http://192.168.1.5:18501",
            dry_run=False,
        )

    def test_tunnel_ingress_upsert_rejects_embedded_credentials(self):
        with self.assertRaisesRegex(ValueError, "credentials_or_fragment_forbidden"):
            ag44.cloudflare_tunnel_ingress_upsert(
                "infralens.creatorcore.ai",
                "http://user:secret@192.168.1.5:18501",
            )


if __name__ == "__main__":
    unittest.main()
