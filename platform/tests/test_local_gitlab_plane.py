from __future__ import annotations

import unittest
from unittest import mock

from raphiia_openai import local_gitlab_plane as gl
from raphiia_openai import tool_catalog
from raphiia_openai.mcp_catalog import tool_catalog as diagnostic_tool_catalog


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
            mock.patch.object(gl, "project_summary", return_value={"ok": True, "project": {"visibility": "private"}}),
            mock.patch.object(gl, "_github_public_visibility", return_value={"ok": True, "public": False, "visibility": "private"}),
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

    def test_create_draft_merge_request_allows_gitlab_rails_master_pair(self) -> None:
        with (
            mock.patch.object(gl, "project_summary", side_effect=[
                {"ok": True, "project": {"id": 101, "path_with_namespace": "gitlab-community/gitlab-org/gitlab"}},
                {"ok": True, "project": {"id": 202, "path_with_namespace": "gitlab-org/gitlab"}},
            ]),
            mock.patch.object(gl, "_request") as request,
        ):
            result = gl.create_draft_merge_request(
                source_project="gitlab-community/gitlab-org/gitlab",
                source_branch="chatgpt/630107-mcp-protocol-events-v2",
                target_project="gitlab-org/gitlab",
                target_branch="master",
                title="Instrument MCP initialize and tools/list protocol methods",
                description="Owner-approved draft merge request dry run for GitLab Rails contribution.",
                dry_run=True,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["payload"]["target_branch"], "master")
        request.assert_not_called()

    def test_create_draft_merge_request_rejects_wrong_target_branch_for_gitlab_rails(self) -> None:
        result = gl.create_draft_merge_request(
            source_project="gitlab-community/gitlab-org/gitlab",
            source_branch="chatgpt/630107-mcp-protocol-events-v2",
            target_project="gitlab-org/gitlab",
            target_branch="main",
            title="Instrument MCP initialize and tools/list protocol methods",
            description="Wrong target branch must be rejected before any API request is attempted.",
            dry_run=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "target_branch_not_allowlisted")
        self.assertEqual(result["allowed"], ["master"])

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

    def test_get_merge_request_returns_review_and_pipeline_state(self) -> None:
        payload = {
            "ok": True,
            "data": {
                "id": 1,
                "iid": 256812,
                "title": "Instrument MCP initialize and tools/list protocol methods",
                "state": "opened",
                "draft": True,
                "description": "MR description",
                "author": {"username": "rafagye"},
                "assignees": [{"id": 7, "username": "rafagye", "name": "Rafael Lopez"}],
                "reviewers": [{"id": 8, "username": "reviewer", "name": "Reviewer"}],
                "labels": ["backend"],
                "milestone": {"id": 19, "title": "19.5"},
                "source_branch": "chatgpt/630107-mcp-protocol-events-v2",
                "target_branch": "master",
                "merge_status": "can_be_merged",
                "detailed_merge_status": "mergeable",
                "has_conflicts": False,
                "blocking_discussions_resolved": True,
                "sha": "abc123",
                "web_url": "https://gitlab.com/gitlab-org/gitlab/-/merge_requests/256812",
                "pipeline": {"id": 900, "status": "running", "web_url": "https://gitlab/p/900"},
                "head_pipeline": {"id": 901, "status": "success", "web_url": "https://gitlab/p/901"},
            },
        }
        with mock.patch.object(gl, "_request", return_value=payload) as request:
            result = gl.get_merge_request("gitlab-org/gitlab", 256812)

        self.assertTrue(result["ok"])
        self.assertTrue(result["merge_request"]["draft"])
        self.assertEqual(result["merge_request"]["reviewers"][0]["username"], "reviewer")
        self.assertEqual(result["merge_request"]["head_pipeline"]["status"], "success")
        request.assert_called_once_with("GET", "/projects/gitlab-org%2Fgitlab/merge_requests/256812")

    def test_list_merge_request_discussions_returns_bounded_notes(self) -> None:
        payload = {
            "ok": True,
            "data": [{
                "id": "d1",
                "individual_note": False,
                "notes": [{
                    "id": 11,
                    "author": {"username": "reviewer"},
                    "body": "Please update the spec.",
                    "system": False,
                    "resolvable": True,
                    "resolved": False,
                    "resolved_by": None,
                    "noteable_type": "MergeRequest",
                    "position": {"new_path": "spec/foo_spec.rb", "new_line": 12},
                }],
            }],
        }
        with mock.patch.object(gl, "_request", return_value=payload) as request:
            result = gl.list_merge_request_discussions("gitlab-org/gitlab", 256812, limit=50)

        self.assertTrue(result["ok"])
        self.assertEqual(result["discussions"][0]["notes"][0]["author"], "reviewer")
        self.assertFalse(result["discussions"][0]["notes"][0]["resolved"])
        request.assert_called_once_with(
            "GET",
            "/projects/gitlab-org%2Fgitlab/merge_requests/256812/discussions",
            query={"per_page": 50},
        )

    def test_list_merge_request_pipelines_uses_mr_endpoint(self) -> None:
        payload = {
            "ok": True,
            "data": [{"id": 901, "iid": 12, "status": "success", "ref": "refs/merge-requests/256812/head", "sha": "abc"}],
        }
        with mock.patch.object(gl, "_request", return_value=payload) as request:
            result = gl.list_merge_request_pipelines("gitlab-org/gitlab", 256812, limit=20)

        self.assertTrue(result["ok"])
        self.assertEqual(result["pipelines"][0]["status"], "success")
        request.assert_called_once_with(
            "GET",
            "/projects/gitlab-org%2Fgitlab/merge_requests/256812/pipelines",
            query={"per_page": 20},
        )

    def test_list_pipeline_jobs_exposes_failure_reason(self) -> None:
        payload = {
            "ok": True,
            "data": [{
                "id": 77,
                "name": "rspec",
                "stage": "test",
                "status": "failed",
                "allow_failure": False,
                "failure_reason": "script_failure",
                "runner": {"id": 4, "description": "saas-linux-medium-amd64"},
            }],
        }
        with mock.patch.object(gl, "_request", return_value=payload) as request:
            result = gl.list_pipeline_jobs("gitlab-org/gitlab", 901, limit=100)

        self.assertTrue(result["ok"])
        self.assertEqual(result["jobs"][0]["failure_reason"], "script_failure")
        request.assert_called_once_with(
            "GET",
            "/projects/gitlab-org%2Fgitlab/pipelines/901/jobs",
            query={"per_page": 100, "include_retried": "true"},
        )

    def test_merge_request_observability_catalog_schemas_are_specific(self) -> None:
        mr_schema = tool_catalog.describe_tool("local_gitlab_get_merge_request")["input_schema"]
        discussions_schema = tool_catalog.describe_tool("local_gitlab_list_merge_request_discussions")["input_schema"]
        pipelines_schema = tool_catalog.describe_tool("local_gitlab_list_merge_request_pipelines")["input_schema"]
        jobs_schema = tool_catalog.describe_tool("local_gitlab_list_pipeline_jobs")["input_schema"]

        self.assertEqual(set(mr_schema), {"project_id_or_path", "mr_iid"})
        self.assertIn("mr_iid", discussions_schema)
        self.assertIn("mr_iid", pipelines_schema)
        self.assertIn("pipeline_id", jobs_schema)

    def test_merge_request_observability_is_in_canonical_mcp_catalog(self) -> None:
        names = {
            "local_gitlab_get_merge_request",
            "local_gitlab_list_merge_request_discussions",
            "local_gitlab_list_merge_request_pipelines",
            "local_gitlab_list_pipeline_jobs",
        }
        self.assertTrue(names.issubset(set(diagnostic_tool_catalog.ALL_MCP_TOOL_NAMES)))
        for name in names:
            described = diagnostic_tool_catalog.describe_tool(name)
            self.assertTrue(described["ok"], name)
            self.assertEqual(described["required_scopes"], ["ralfia:read"])

    def test_get_issue_returns_bounded_detail(self) -> None:
        payload = {
            "ok": True,
            "data": {
                "id": 9,
                "iid": 607885,
                "title": "MCP naming",
                "state": "opened",
                "labels": ["Seeking community contributions", "community-bonus::200"],
                "description": "Issue details",
                "assignees": [{"id": 7, "username": "rafagye", "name": "Rafael Lopez"}],
                "milestone": {"id": 19, "title": "19.5"},
                "web_url": "https://gitlab.com/gitlab-org/gitlab/-/issues/607885",
            },
        }
        with mock.patch.object(gl, "_request", return_value=payload) as request:
            result = gl.get_issue("gitlab-org/gitlab", 607885)

        self.assertTrue(result["ok"])
        self.assertEqual(result["issue"]["assignees"][0]["username"], "rafagye")
        self.assertEqual(result["issue"]["milestone"]["title"], "19.5")
        request.assert_called_once_with("GET", "/projects/gitlab-org%2Fgitlab/issues/607885")

    def test_comment_issue_rejects_quick_actions(self) -> None:
        with mock.patch.object(gl, "_request") as request:
            result = gl.comment_issue("gitlab-org/gitlab", 607885, "Working on it\n/assign @rafagye", dry_run=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "quick_actions_not_allowed_in_comment_issue")
        request.assert_not_called()

    def test_comment_issue_posts_only_when_not_dry_run(self) -> None:
        response = {
            "ok": True,
            "data": {
                "id": 42,
                "body": "Working on this.",
                "author": {"username": "rafagye"},
                "created_at": "2026-09-15T00:00:00Z",
            },
        }
        with mock.patch.object(gl, "_request", return_value=response) as request, mock.patch.object(gl, "_audit"):
            result = gl.comment_issue("gitlab-org/gitlab", 607885, "Working on this.", dry_run=False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["note"]["author"], "rafagye")
        request.assert_called_once_with(
            "POST",
            "/projects/gitlab-org%2Fgitlab/issues/607885/notes",
            payload={"body": "Working on this."},
        )

    def test_claim_issue_refuses_closed_issue(self) -> None:
        with (
            mock.patch.object(gl, "gitlab_status", return_value={"auth_ok": True, "verified_user": {"id": 7, "username": "rafagye"}}),
            mock.patch.object(gl, "get_issue", return_value={"ok": True, "issue": {"state": "closed", "labels": ["Seeking community contributions"], "assignees": []}}),
            mock.patch.object(gl, "_request") as request,
        ):
            result = gl.claim_issue("gitlab-org/gitlab", 607885, dry_run=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "issue_not_open")
        request.assert_not_called()

    def test_claim_issue_refuses_other_assignee(self) -> None:
        issue = {
            "state": "opened",
            "labels": ["Seeking community contributions"],
            "assignees": [{"id": 8, "username": "someone_else"}],
        }
        with (
            mock.patch.object(gl, "gitlab_status", return_value={"auth_ok": True, "verified_user": {"id": 7, "username": "rafagye"}}),
            mock.patch.object(gl, "get_issue", return_value={"ok": True, "issue": issue}),
            mock.patch.object(gl, "_request") as request,
        ):
            result = gl.claim_issue("gitlab-org/gitlab", 607885, dry_run=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "issue_already_assigned")
        request.assert_not_called()

    def test_claim_issue_requires_community_label_by_default(self) -> None:
        issue = {"state": "opened", "labels": ["backend"], "assignees": []}
        with (
            mock.patch.object(gl, "gitlab_status", return_value={"auth_ok": True, "verified_user": {"id": 7, "username": "rafagye"}}),
            mock.patch.object(gl, "get_issue", return_value={"ok": True, "issue": issue}),
            mock.patch.object(gl, "_request") as request,
        ):
            result = gl.claim_issue("gitlab-org/gitlab", 607885, dry_run=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "required_label_missing")
        request.assert_not_called()

    def test_claim_issue_assigns_only_authenticated_user(self) -> None:
        current = {
            "state": "opened",
            "labels": ["Seeking community contributions"],
            "assignees": [],
            "iid": 607885,
        }
        updated = {
            "ok": True,
            "data": {
                "iid": 607885,
                "title": "MCP naming",
                "state": "opened",
                "labels": ["Seeking community contributions"],
                "assignees": [{"id": 7, "username": "rafagye"}],
            },
        }
        with (
            mock.patch.object(gl, "gitlab_status", return_value={"auth_ok": True, "verified_user": {"id": 7, "username": "rafagye"}}),
            mock.patch.object(gl, "get_issue", return_value={"ok": True, "issue": current}),
            mock.patch.object(gl, "_request", return_value=updated) as request,
            mock.patch.object(gl, "_audit"),
        ):
            result = gl.claim_issue("gitlab-org/gitlab", 607885, username="rafagye", dry_run=False)

        self.assertTrue(result["ok"])
        self.assertTrue(result["claimed"])
        request.assert_called_once_with(
            "PUT",
            "/projects/gitlab-org%2Fgitlab/issues/607885",
            payload={"assignee_ids": [7]},
        )

    def test_claim_issue_reports_maintainer_gate(self) -> None:
        current = {
            "state": "opened",
            "labels": ["Seeking community contributions"],
            "assignees": [],
        }
        with (
            mock.patch.object(gl, "gitlab_status", return_value={"auth_ok": True, "verified_user": {"id": 7, "username": "rafagye"}}),
            mock.patch.object(gl, "get_issue", return_value={"ok": True, "issue": current}),
            mock.patch.object(gl, "_request", return_value={"ok": False, "status": 403, "error": "gitlab_http_error"}),
            mock.patch.object(gl, "_audit"),
        ):
            result = gl.claim_issue("gitlab-org/gitlab", 607885, dry_run=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "assignment_requires_maintainer_or_contributor_platform")

    def test_issue_write_tool_catalog_schemas_are_specific(self) -> None:
        get_schema = tool_catalog.describe_tool("local_gitlab_get_issue")["input_schema"]
        comment_schema = tool_catalog.describe_tool("local_gitlab_comment_issue")["input_schema"]
        claim_schema = tool_catalog.describe_tool("local_gitlab_claim_issue")["input_schema"]
        self.assertEqual(set(get_schema), {"project_id_or_path", "issue_iid"})
        self.assertIn("body", comment_schema)
        self.assertIn("dry_run", comment_schema)
        self.assertIn("require_label", claim_schema)
        self.assertIn("username", claim_schema)


if __name__ == "__main__":
    unittest.main()
