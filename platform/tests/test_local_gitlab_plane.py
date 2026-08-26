from __future__ import annotations

import unittest
from unittest import mock

from raphiia_openai import local_gitlab_plane as gl


class LocalGitLabPlaneTests(unittest.TestCase):
    def test_project_path_is_url_encoded(self) -> None:
        self.assertEqual(gl.project_api_path("rafagye/demo-repo"), "rafagye%2Fdemo-repo")

    def test_redact_removes_tokens(self) -> None:
        text = "PRIVATE-TOKEN: glpat-abcdefghijklmnop and Authorization=Bearer abc.def.ghi"
        redacted = gl._redact(text)
        self.assertNotIn("glpat-", redacted)
        self.assertNotIn("abc.def.ghi", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_status_without_token_is_non_destructive_blocked_lane(self) -> None:
        with mock.patch.object(gl, "_token", return_value=("", "missing")), mock.patch.object(gl, "_which", return_value=None):
            status = gl.gitlab_status()
        self.assertTrue(status["ok"])
        self.assertFalse(status["token_present"])
        self.assertFalse(status["auth_ok"])
        self.assertEqual(status["blocker"], "gitlab_token_missing")

    def test_resource_provider_dry_run_never_default_engine(self) -> None:
        with mock.patch.object(gl, "gitlab_status", return_value={"auth_ok": False, "verified_user": None}):
            result = gl.register_resource_provider(dry_run=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["provider"]["local_first"])
        self.assertEqual(result["provider"]["cost_policy"], "external_specialized_not_default")
        self.assertFalse(result["model"]["default_enabled"])
        self.assertNotIn("coding", result["model"]["task_classes"])
        self.assertNotIn("heavy_reasoning", result["model"]["task_classes"])

    def test_credit_dry_run_marks_credits_not_gastable(self) -> None:
        fake_collection = mock.Mock()
        fake_collection.find.return_value = []
        fake_db = {"funding_credit_accounts": fake_collection}
        with mock.patch.object(gl.mongo_store, "get_db", return_value=fake_db):
            result = gl.gitlab_credit_status(register_if_missing=True, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["registered_new"])
        self.assertEqual(result["account"]["balance"], 80)
        self.assertEqual(result["account"]["status"], "paused")
        self.assertIn("not_gastable", result["account"]["metadata"]["spend_policy"])


if __name__ == "__main__":
    unittest.main()
