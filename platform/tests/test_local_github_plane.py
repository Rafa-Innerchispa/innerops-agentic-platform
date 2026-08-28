from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path

from raphiia_openai import local_github_plane


class LocalGithubPlaneTests(unittest.TestCase):
    def test_rejects_non_allowlisted_owner(self) -> None:
        result = local_github_plane.create_github_repo(
            owner="OtherOrg",
            name="example",
            actor="chatgpt",
            task_id="ops_test",
            correlation_id="corr_test",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "github_owner_not_allowlisted")

    def test_rejects_invalid_repo_name(self) -> None:
        result = local_github_plane.create_github_repo(
            owner="Rafa-Innerchispa",
            name="../bad",
            actor="chatgpt",
            task_id="ops_test",
            correlation_id="corr_test",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_repo_name")

    def test_bootstrap_project_without_remote_creates_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_roots = os.environ.get("RALFIA_FS_ROOTS_JSON")
            old_audit = os.environ.get("RALFIA_FS_DISABLE_AUDIT")
            os.environ["RALFIA_FS_ROOTS_JSON"] = json.dumps([str(root)])
            os.environ["RALFIA_FS_DISABLE_AUDIT"] = "1"
            try:
                result = local_github_plane.bootstrap_project(
                    path=str(root),
                    project_name="innerops-example",
                    actor="chatgpt",
                    task_id="ops_test",
                    correlation_id="corr_test",
                    description="Example project.",
                    create_remote=False,
                )
            finally:
                if old_roots is None:
                    os.environ.pop("RALFIA_FS_ROOTS_JSON", None)
                else:
                    os.environ["RALFIA_FS_ROOTS_JSON"] = old_roots
                if old_audit is None:
                    os.environ.pop("RALFIA_FS_DISABLE_AUDIT", None)
                else:
                    os.environ["RALFIA_FS_DISABLE_AUDIT"] = old_audit

            self.assertTrue(result["ok"], result)
            project_dir = root / "innerops-example"
            self.assertTrue((project_dir / "README.md").exists())
            self.assertTrue((project_dir / ".git").exists())
            self.assertIsNone(result["remote"])

    def test_status_is_redacted_and_non_mutating(self) -> None:
        old_token = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "github_pat_sensitive"
        try:
            status = local_github_plane.github_status()
        finally:
            if old_token is None:
                os.environ.pop("GITHUB_TOKEN", None)
            else:
                os.environ["GITHUB_TOKEN"] = old_token

        self.assertTrue(status["ok"])
        self.assertTrue(status["env_token_present"])
        self.assertNotIn("github_pat_sensitive", str(status))


if __name__ == "__main__":
    unittest.main()
