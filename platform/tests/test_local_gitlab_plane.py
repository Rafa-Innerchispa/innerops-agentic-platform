from __future__ import annotations

import unittest
from unittest import mock

from raphiia_openai import local_gitlab_plane as gl
from raphiia_openai import tool_catalog


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

    def test_user_profile_without_username_uses_status(self) -> None:
        with mock.patch.object(gl, "gitlab_status", return_value={"auth_ok": True, "verified_user": {"username": "rafagye"}}):
            result = gl.user_profile()
        self.assertTrue(result["ok"])
        self.assertEqual(result["profile"]["username"], "rafagye")

    def test_discover_contribution_issues_requires_token_but_is_read_only(self) -> None:
        with mock.patch.object(gl, "_request", return_value={"ok": True, "data": [{"id": 1, "title": "Fix docs", "labels": ["documentation"]}]}):
            result = gl.discover_contribution_issues(search="docs")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)

    def test_prepare_mirror_push_uses_noninteractive_gitlab_auth(self) -> None:
        repo = {
            "source_path": "/tmp/demo",
            "github_owner": "Rafa-Innerchispa",
            "github_repo": "demo",
            "head_sha": "abc123",
            "remotes": {"gitlab": {"fetch": "https://gitlab.com/rafagye/demo.git"}},
        }
        calls: list[tuple[list[str], dict[str, str]]] = []

        def fake_run_with_env(argv: list[str], env: dict[str, str], timeout: int = 30):
            calls.append((argv, env))
            return {"ok": True, "returncode": 0, "stdout": "", "stderr": "", "argv": argv}

        with (
            mock.patch.object(gl, "gitlab_status", return_value={"auth_ok": True}),
            mock.patch.object(gl, "_discover_github_worktrees", return_value=[repo]),
            mock.patch.object(gl, "project_summary", return_value={"ok": True}),
            mock.patch.object(gl, "_namespaces", return_value=["rafagye"]),
            mock.patch.object(gl, "_gitlab_git_auth_env") as auth_env,
            mock.patch.object(gl, "_run_with_env", side_effect=fake_run_with_env),
            mock.patch.object(gl, "_audit"),
        ):
            auth_env.return_value.__enter__.return_value = {"GIT_ASKPASS": "/tmp/askpass", "GIT_TERMINAL_PROMPT": "0"}
            auth_env.return_value.__exit__.return_value = None
            result = gl.prepare_github_mirrors(namespace="rafagye", configure_remotes=False, push=True, dry_run=False)

        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(env["GIT_TERMINAL_PROMPT"] == "0" for _, env in calls))
        self.assertIn("push", calls[0][0])

    def test_create_draft_merge_request_dry_run_is_allowlisted(self) -> None:
        with (
            mock.patch.object(gl, "project_summary", side_effect=[
                {"ok": True, "project": {"id": 101, "path_with_namespace": "gitlab-community/gitlab-org/gitlab-runner"}},
                {"ok": True, "project": {"id": 202, "path_with_namespace": "gitlab-org/gitlab-runner"}},
            ]),
            mock.patch.object(gl, "_request") as request,
        ):
            result = gl.create_draft_merge_request(
                source_project="gitlab-community/gitlab-org/gitlab-runner",
                source_branch="chatgpt/fix/39708-cache-url-redaction",
                target_project="gitlab-org/gitlab-runner",
                target_branch="main",
                title="Fix cache URL redaction docs",
                description="Owner-approved draft merge request dry run for GitLab Runner contribution.",
                dry_run=True,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["payload"]["title"].startswith("Draft:"))
        self.assertEqual(result["payload"]["target_project_id"], 202)
        request.assert_not_called()

    def test_create_draft_merge_request_rejects_unallowlisted_pair(self) -> None:
        result = gl.create_draft_merge_request(
            source_project="rafagye/demo",
            source_branch="chatgpt/fix/demo",
            target_project="gitlab-org/gitlab-runner",
            title="Demo",
            description="This should be rejected before any API call.",
            dry_run=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "merge_request_pair_not_allowlisted")

    def test_create_draft_merge_request_posts_only_when_not_dry_run(self) -> None:
        created = {
            "ok": True,
            "data": {
                "id": 1,
                "iid": 77,
                "title": "Draft: Fix cache URL redaction docs",
                "state": "opened",
                "source_branch": "chatgpt/fix/39708-cache-url-redaction",
                "target_branch": "main",
                "web_url": "https://gitlab.com/gitlab-org/gitlab-runner/-/merge_requests/77",
            },
        }
        with (
            mock.patch.object(gl, "project_summary", side_effect=[
                {"ok": True, "project": {"id": 101, "path_with_namespace": "gitlab-community/gitlab-org/gitlab-runner"}},
                {"ok": True, "project": {"id": 202, "path_with_namespace": "gitlab-org/gitlab-runner"}},
            ]),
            mock.patch.object(gl, "_request", return_value=created) as request,
        ):
            result = gl.create_draft_merge_request(
                source_project="gitlab-community/gitlab-org/gitlab-runner",
                source_branch="chatgpt/fix/39708-cache-url-redaction",
                target_project="gitlab-org/gitlab-runner",
                title="Fix cache URL redaction docs",
                description="Owner-approved draft merge request creation after branch push has succeeded.",
                dry_run=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["merge_request"]["iid"], 77)
        request.assert_called_once()

    def test_draft_merge_request_catalog_schema_is_specific(self) -> None:
        described = tool_catalog.describe_tool("local_gitlab_create_draft_merge_request")
        self.assertTrue(described["ok"])
        schema = described["input_schema"]
        self.assertIn("source_project", schema)
        self.assertIn("source_branch", schema)
        self.assertIn("target_project", schema)
        self.assertIn("title", schema)
        self.assertNotIn("project_id_or_path", schema)


if __name__ == "__main__":
    unittest.main()
