from __future__ import annotations

import os
import json
import tempfile
import unittest
from unittest import mock
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

    def test_professionalization_audit_summarizes_repos(self) -> None:
        repos = [
            {"name": "innerops-agentic-platform", "nameWithOwner": "Rafa-Innerchispa/innerops-agentic-platform", "isPrivate": False, "isArchived": False, "description": "Platform", "homepageUrl": "", "repositoryTopics": [], "url": "https://github.com/Rafa-Innerchispa/innerops-agentic-platform", "defaultBranchRef": {"name": "main"}},
            {"name": "demo-hackathon", "nameWithOwner": "Rafa-Innerchispa/demo-hackathon", "isPrivate": False, "isArchived": False, "description": "", "homepageUrl": "", "repositoryTopics": [], "url": "https://github.com/Rafa-Innerchispa/demo-hackathon", "defaultBranchRef": {"name": "main"}},
        ]

        def fake_run(argv, **kwargs):
            if argv[:3] == ["/usr/bin/gh", "repo", "list"]:
                return {"ok": True, "returncode": 0, "stdout": json.dumps(repos), "stderr": "", "argv": argv}
            if argv[:2] == ["/usr/bin/gh", "api"] and argv[2].startswith("repos/"):
                return {"ok": True, "returncode": 0, "stdout": json.dumps({"permissions": {"push": True}, "archived": False, "disabled": False, "default_branch": "main"}), "stderr": "", "argv": argv}
            if argv[:2] == ["/usr/bin/gh", "auth"]:
                return {"ok": True, "returncode": 0, "stdout": "", "stderr": "Token scopes: 'repo', 'workflow'", "argv": argv}
            return {"ok": True, "returncode": 0, "stdout": "{}", "stderr": "", "argv": argv}

        with mock.patch.object(local_github_plane, "_gh_path", return_value="/usr/bin/gh"), mock.patch.object(local_github_plane, "_run", side_effect=fake_run):
            result = local_github_plane.audit_github_professionalization(include_rows=True)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["repo_count"], 2)
        self.assertEqual(result["metadata_dryrun_eligible_count"], 1)
        self.assertEqual(result["freeze_review_required_count"], 1)
        self.assertEqual(result["bio_pins_minimum_missing_oauth_scope_classic_pat"], "user")

    def test_update_repo_profile_dry_run_blocks_frozen_hackathon(self) -> None:
        with mock.patch.object(local_github_plane, "_gh_path", return_value="/usr/bin/gh"), mock.patch.object(local_github_plane, "_repo_view", return_value=({"ok": True}, {"permissions": {"push": True}, "archived": False, "disabled": False})):
            result = local_github_plane.update_repo_professionalization(
                owner="Rafa-Innerchispa",
                name="demo-hackathon",
                actor="chatgpt",
                task_id="ops_test",
                correlation_id="corr_test",
                description="Demo",
                topics=["InnerOS", "ai-agents"],
                dry_run=True,
            )

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["plan"]["topics"], ["inneros", "ai-agents"])
        self.assertEqual(result["blocked_for_apply"], "hackathon_or_submission_freeze_review_required")

    def test_update_owner_profile_requires_user_scope_for_apply(self) -> None:
        with mock.patch.object(local_github_plane, "_gh_path", return_value="/usr/bin/gh"), mock.patch.object(local_github_plane, "_current_scopes", return_value=["repo"]):
            result = local_github_plane.update_owner_profile(
                actor="chatgpt",
                task_id="ops_test",
                correlation_id="corr_test",
                dry_run=False,
                bio="InnerOS builder",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["required_scope"], "user")
        self.assertEqual(result["blocked_for_apply"], "missing_github_user_scope")

    def test_pin_repositories_is_additive_and_requires_user_scope(self) -> None:
        with mock.patch.object(local_github_plane, "_gh_path", return_value="/usr/bin/gh"), mock.patch.object(local_github_plane, "_current_scopes", return_value=["repo"]), mock.patch.object(local_github_plane, "_repo_view", return_value=({"ok": True}, {"node_id": "R_123"})):
            result = local_github_plane.pin_repositories(
                owner="Rafa-Innerchispa",
                repositories=["innerops-agentic-platform"],
                actor="chatgpt",
                task_id="ops_test",
                correlation_id="corr_test",
                dry_run=False,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["plan"]["pin_repositories_additive_only"], ["Rafa-Innerchispa/innerops-agentic-platform"])
        self.assertEqual(result["blocked_for_apply"], "missing_github_user_scope")


if __name__ == "__main__":
    unittest.main()
