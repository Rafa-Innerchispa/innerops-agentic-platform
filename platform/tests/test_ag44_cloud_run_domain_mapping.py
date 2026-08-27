from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime.agents import ag44_cloud_deployer as ag44


class CloudRunDomainMappingTests(unittest.TestCase):
    def test_status_uses_describe_and_surfaces_resource_records(self):
        records = [{"name": "inneros.creatoros.dev.", "rrdata": "ghs.googlehosted.com.", "type": "CNAME"}]
        with patch.object(
            ag44,
            "_gcp_read_json",
            return_value={"ok": True, "data": {"status": {"resourceRecords": records}}},
        ) as read_json:
            result = ag44.gcp_cloud_run_domain_mapping_status(
                "innerops-agentic-platform", "inneros.creatoros.dev", region="us-central1"
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["resource_records"], records)
        read_json.assert_called_once_with(
            "gcp_cloud_run_domain_mapping_status",
            [
                "beta", "run", "domain-mappings", "describe",
                "--domain", "inneros.creatoros.dev",
                "--region", "us-central1",
                "--project", "innerops-agentic-platform",
                "--format=json",
            ],
            timeout=60,
        )

    def test_create_builds_gated_google_command(self):
        with patch.object(
            ag44,
            "_gcp_apply_validation",
            return_value={"ok": True, "dry_run": True, "project_id": "innerops-agentic-platform"},
        ), patch.object(ag44, "_gcp_candidate", return_value={"ok": True, "executed": False}) as candidate:
            result = ag44.gcp_cloud_run_domain_mapping_create(
                "innerops-agentic-platform",
                "inneros",
                "inneros.creatoros.dev",
                region="us-central1",
                dry_run=True,
            )

        self.assertTrue(result["ok"])
        command = candidate.call_args.args[2]
        self.assertEqual(
            command,
            [
                "gcloud", "beta", "run", "domain-mappings", "create",
                "--service", "inneros",
                "--domain", "inneros.creatoros.dev",
                "--region", "us-central1",
                "--project", "innerops-agentic-platform",
                "--quiet",
            ],
        )

    def test_create_rejects_domain_outside_owned_cloudflare_zones(self):
        with patch.object(
            ag44,
            "_gcp_apply_validation",
            return_value={"ok": True, "dry_run": True, "project_id": "innerops-agentic-platform"},
        ):
            result = ag44.gcp_cloud_run_domain_mapping_create(
                "innerops-agentic-platform",
                "inneros",
                "inneros.example.net",
                dry_run=True,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "domain_not_allowlisted")


if __name__ == "__main__":
    unittest.main()
