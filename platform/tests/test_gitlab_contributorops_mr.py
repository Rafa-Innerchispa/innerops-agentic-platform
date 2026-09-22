from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gitlab_contributorops_mr.py"
SPEC = importlib.util.spec_from_file_location("gitlab_contributorops_mr", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _mr_payload(*, draft: bool = True, title: str = "Draft: Instrument MCP initialize and tools/list protocol methods"):
    return {
        "id": 1,
        "iid": 256812,
        "title": title,
        "state": "opened",
        "draft": draft,
        "author": {"username": "rafagye"},
        "source_project_id": 101,
        "source_branch": "chatgpt/630107-mcp-protocol-events-v2",
        "target_branch": "master",
        "sha": "5f61a3974db4",
        "web_url": "https://gitlab.com/gitlab-org/gitlab/-/merge_requests/256812",
        "labels": ["backend"],
        "milestone": None,
        "blocking_discussions_resolved": True,
    }


def _status():
    return {"auth_ok": True, "verified_user": {"username": "rafagye"}}


def test_inspect_marks_green_owner_mr_ready_to_mark() -> None:
    with (
        mock.patch.object(mod.gl, "gitlab_status", return_value=_status()),
        mock.patch.object(mod.gl, "_request", return_value={"ok": True, "data": _mr_payload()}),
        mock.patch.object(mod.gl, "project_summary", return_value={
            "ok": True,
            "project": {"path_with_namespace": "gitlab-community/gitlab-org/gitlab"},
        }),
        mock.patch.object(mod.gl, "list_merge_request_pipelines", return_value={
            "ok": True,
            "pipelines": [{"id": 2869995317, "status": "success"}],
        }),
        mock.patch.object(mod.gl, "list_merge_request_discussions", return_value={
            "ok": True,
            "discussions": [{"id": "d1", "notes": [{"id": 1, "resolvable": True, "resolved": True}]}],
        }),
    ):
        result = mod.inspect("gitlab-org/gitlab", 256812)

    assert result["ok"] is True
    assert result["ready_to_mark"] is True
    assert all(result["guards"].values())


def test_inspect_blocks_when_pipeline_failed_or_discussion_open() -> None:
    with (
        mock.patch.object(mod.gl, "gitlab_status", return_value=_status()),
        mock.patch.object(mod.gl, "_request", return_value={"ok": True, "data": _mr_payload()}),
        mock.patch.object(mod.gl, "project_summary", return_value={
            "ok": True,
            "project": {"path_with_namespace": "gitlab-community/gitlab-org/gitlab"},
        }),
        mock.patch.object(mod.gl, "list_merge_request_pipelines", return_value={
            "ok": True,
            "pipelines": [{"id": 1, "status": "failed"}],
        }),
        mock.patch.object(mod.gl, "list_merge_request_discussions", return_value={
            "ok": True,
            "discussions": [{"id": "d1", "notes": [{
                "id": 2,
                "author": "reviewer",
                "body": "Please fix",
                "resolvable": True,
                "resolved": False,
            }]}],
        }),
    ):
        result = mod.inspect("gitlab-org/gitlab", 256812)

    assert result["ok"] is True
    assert result["ready_to_mark"] is False
    assert result["guards"]["latest_pipeline_success"] is False
    assert result["guards"]["no_unresolved_discussions"] is False


def test_mark_ready_dry_run_strips_only_draft_prefix() -> None:
    ready_report = {
        "ok": True,
        "ready_to_mark": True,
        "draft": True,
        "title": "Draft: Instrument MCP initialize and tools/list protocol methods",
    }
    with mock.patch.object(mod, "inspect", return_value=ready_report):
        result = mod.mark_ready("gitlab-org/gitlab", 256812, apply=False)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_update"]["title"] == "Instrument MCP initialize and tools/list protocol methods"


def test_mark_ready_applies_title_update_and_verifies() -> None:
    before = {
        "ok": True,
        "ready_to_mark": True,
        "draft": True,
        "title": "Draft: Instrument MCP initialize and tools/list protocol methods",
    }
    after = {
        "ok": True,
        "ready_to_mark": True,
        "draft": False,
        "title": "Instrument MCP initialize and tools/list protocol methods",
    }
    with (
        mock.patch.object(mod, "inspect", side_effect=[before, after]),
        mock.patch.object(mod.gl, "_request", return_value={"ok": True, "data": _mr_payload(draft=False)}) as request,
    ):
        result = mod.mark_ready("gitlab-org/gitlab", 256812, apply=True)

    assert result["ok"] is True
    assert result["applied"] is True
    assert result["verified_ready"] is True
    request.assert_called_once()
    payload = request.call_args.kwargs["payload"]
    assert payload == {"title": "Instrument MCP initialize and tools/list protocol methods"}


def test_pick_review_labels_uses_exact_danger_labels_only() -> None:
    rows = [
        {"id": 1, "name": "analytics instrumentation"},
        {"id": 2, "name": "analytics instrumentation::review pending"},
        {"id": 3, "name": "roulette-experiment::reviewer-column-shown"},
        {"id": 4, "name": "roulette-experiment::reviewer-column-hidden"},
        {"id": 5, "name": "backend"},
    ]

    selected = mod._pick_review_labels(rows)

    assert [row["name"] for row in selected] == [
        "analytics instrumentation",
        "analytics instrumentation::review pending",
        "roulette-experiment::reviewer-column-hidden",
        "backend",
    ]


def test_milestone_rows_falls_back_to_gitlab_org_group() -> None:
    with mock.patch.object(
        mod.gl,
        "_request",
        side_effect=[
            {"ok": True, "data": []},
            {"ok": True, "data": [{"id": 6239396, "title": "19.5"}]},
        ],
    ) as request:
        rows = mod._milestone_rows("gitlab-org/gitlab", "19.5")

    assert rows == [{"id": 6239396, "title": "19.5"}]
    assert request.call_args_list[1].args[1] == "/groups/gitlab-org/milestones"


def test_apply_review_metadata_dry_run_preserves_existing_labels() -> None:
    report = {
        "ok": True,
        "guards": {"authenticated_user_is_author": True, "state_open": True},
        "review_metadata": {
            "milestone": {"id": 6239396, "title": "19.5"},
            "selected_labels": [
                {"id": 1, "name": "analytics instrumentation"},
                {"id": 2, "name": "analytics instrumentation::review pending"},
                {"id": 3, "name": "roulette-experiment::reviewer-column-hidden"},
                {"id": 4, "name": "backend"},
            ],
        },
        "labels": ["Community contribution"],
    }
    with mock.patch.object(mod, "discover_review_metadata", return_value=report):
        result = mod.apply_review_metadata("gitlab-org/gitlab", 256812, apply=False)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_update"]["milestone_id"] == 6239396
    assert result["would_update"]["add_labels"] == (
        "analytics instrumentation,"
        "analytics instrumentation::review pending,"
        "roulette-experiment::reviewer-column-hidden,"
        "backend"
    )


def test_request_human_review_dry_run_preserves_existing_reviewers() -> None:
    report = {
        "ok": True,
        "draft": False,
        "guards": {
            "authenticated_user_is_author": True,
            "latest_pipeline_success": True,
            "no_unresolved_discussions": True,
            "state_open": True,
        },
    }
    raw = {
        "ok": True,
        "data": {
            "reviewers": [{"id": 99, "username": "GitLabDuo"}],
        },
    }
    with (
        mock.patch.object(mod, "inspect", return_value=report),
        mock.patch.object(mod, "_gitlab_user", return_value={
            "id": 15705892,
            "username": "panoskanell",
        }),
        mock.patch.object(mod, "_raw_mr", return_value=raw),
        mock.patch.object(mod, "_review_request_note_exists", return_value=False),
    ):
        result = mod.request_human_review(
            "gitlab-org/gitlab",
            256812,
            reviewer="panoskanell",
            apply=False,
        )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_update"]["reviewer_ids"] == [99, 15705892]
    assert mod.REVIEW_REQUEST_MARKER in result["would_update"]["comment"]


def test_request_human_review_is_idempotent_when_already_requested() -> None:
    report = {
        "ok": True,
        "draft": False,
        "guards": {
            "authenticated_user_is_author": True,
            "latest_pipeline_success": True,
            "no_unresolved_discussions": True,
            "state_open": True,
        },
    }
    raw = {
        "ok": True,
        "data": {
            "reviewers": [{"id": 15705892, "username": "panoskanell"}],
        },
    }
    with (
        mock.patch.object(mod, "inspect", return_value=report),
        mock.patch.object(mod, "_gitlab_user", return_value={
            "id": 15705892,
            "username": "panoskanell",
        }),
        mock.patch.object(mod, "_raw_mr", return_value=raw),
        mock.patch.object(mod, "_review_request_note_exists", return_value=True),
        mock.patch.object(mod.gl, "_request") as request,
    ):
        result = mod.request_human_review(
            "gitlab-org/gitlab",
            256812,
            reviewer="panoskanell",
            apply=True,
        )

    assert result["applied"] is True
    assert result["reviewer_update"]["skipped"] is True
    assert result["note_update"]["skipped"] is True
    request.assert_not_called()


def test_gitlab_user_rejects_unallowlisted_reviewer() -> None:
    with mock.patch.object(mod.gl, "_request") as request:
        result = mod._gitlab_user("someone-else")

    assert result is None
    request.assert_not_called()


def test_rebase_dry_run_reports_conflict_preflight() -> None:
    report = {
        "ok": True,
        "draft": False,
        "guards": {
            "authenticated_user_is_author": True,
            "source_project_allowlisted": True,
            "source_branch_allowlisted": True,
            "state_open": True,
        },
    }
    raw = {
        "ok": True,
        "data": {
            "has_conflicts": True,
            "merge_status": "cannot_be_merged",
            "detailed_merge_status": "not_approved",
            "sha": "5f61a397",
        },
    }
    with (
        mock.patch.object(mod, "inspect", return_value=report),
        mock.patch.object(mod, "_raw_mr", return_value=raw),
    ):
        result = mod.rebase_merge_request("gitlab-org/gitlab", 256812, apply=False)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["preflight"]["has_conflicts"] is True
    assert result["would_request"]["skip_ci"] is False


def test_rebase_apply_polls_until_complete() -> None:
    before = {
        "ok": True,
        "draft": False,
        "guards": {
            "authenticated_user_is_author": True,
            "source_project_allowlisted": True,
            "source_branch_allowlisted": True,
            "state_open": True,
        },
    }
    after = {
        "ok": True,
        "draft": False,
        "guards": before["guards"],
        "latest_pipeline": {"status": "pending"},
    }
    raw = {
        "ok": True,
        "data": {
            "has_conflicts": False,
            "merge_status": "can_be_merged",
            "detailed_merge_status": "mergeable",
            "sha": "oldsha",
        },
    }
    queued = {"ok": True, "status": 202, "data": {"rebase_in_progress": True}}
    final = {
        "ok": True,
        "status": 200,
        "data": {
            "rebase_in_progress": False,
            "merge_error": None,
            "sha": "newsha",
            "has_conflicts": False,
            "detailed_merge_status": "checking",
        },
    }
    with (
        mock.patch.object(mod, "inspect", side_effect=[before, after]),
        mock.patch.object(mod, "_raw_mr", return_value=raw),
        mock.patch.object(mod.gl, "_request", side_effect=[queued, final]) as request,
    ):
        result = mod.rebase_merge_request("gitlab-org/gitlab", 256812, apply=True)

    assert result["ok"] is True
    assert result["applied"] is True
    assert result["merge_error"] is None
    assert result["post_rebase_sha"] == "newsha"
    assert request.call_args_list[0].args[0] == "PUT"
    assert request.call_args_list[1].kwargs["query"] == {"include_rebase_in_progress": "true"}


def test_rebase_enqueue_failure_is_reported_without_mutation_claim() -> None:
    report = {
        "ok": True,
        "draft": False,
        "guards": {
            "authenticated_user_is_author": True,
            "source_project_allowlisted": True,
            "source_branch_allowlisted": True,
            "state_open": True,
        },
    }
    raw = {"ok": True, "data": {"has_conflicts": True, "sha": "oldsha"}}
    denied = {"ok": False, "status": 403, "error": "Cannot push to source branch"}
    with (
        mock.patch.object(mod, "inspect", return_value=report),
        mock.patch.object(mod, "_raw_mr", return_value=raw),
        mock.patch.object(mod.gl, "_request", return_value=denied),
    ):
        result = mod.rebase_merge_request("gitlab-org/gitlab", 256812, apply=True)

    assert result["ok"] is False
    assert result["error"] == "rebase_enqueue_failed"
    assert result["applied"] is False


def _api_commit_report(sha: str = "5f61a3974db42965efd57c7041d72c0542c09fec") -> dict:
    return {
        "ok": True,
        "sha": sha,
        "source_project": "gitlab-community/gitlab-org/gitlab",
        "source_branch": "chatgpt/630107-mcp-protocol-events-v2",
        "guards": {
            "authenticated_user_is_author": True,
            "source_project_allowlisted": True,
            "source_branch_allowlisted": True,
            "state_open": True,
        },
    }


def test_commit_worktree_files_rejects_source_sha_mismatch(tmp_path: Path) -> None:
    with mock.patch.object(mod, "inspect", return_value=_api_commit_report()):
        result = mod.commit_worktree_files(
            "gitlab-org/gitlab",
            256812,
            expected_sha="a" * 40,
            files=["lib/api/mcp/handlers/list_tools.rb"],
            apply=False,
        )

    assert result["ok"] is False
    assert result["error"] == "source_sha_mismatch"
    assert result["actual_sha"] == "5f61a3974db42965efd57c7041d72c0542c09fec"


def test_commit_worktree_files_dry_run_validates_mr_paths_and_sizes(tmp_path: Path) -> None:
    expected = "5f61a3974db42965efd57c7041d72c0542c09fec"
    file_path = "lib/api/mcp/handlers/list_tools.rb"
    local = tmp_path / file_path
    local.parent.mkdir(parents=True)
    local.write_text("content\n", encoding="utf-8")

    with (
        mock.patch.object(mod, "inspect", return_value=_api_commit_report(expected)),
        mock.patch.object(mod, "_source_worktree_path", return_value=tmp_path),
        mock.patch.object(mod, "_mr_diff_paths", return_value={file_path}),
    ):
        result = mod.commit_worktree_files(
            "gitlab-org/gitlab",
            256812,
            expected_sha=expected,
            files=[file_path],
            apply=False,
        )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["files"] == [{"file_path": file_path, "bytes": 8}]
    assert result["would_commit"]["actions"] == [
        {"action": "update", "file_path": file_path, "bytes": 8}
    ]


def test_commit_worktree_files_rejects_file_outside_mcp_allowlist(tmp_path: Path) -> None:
    expected = "5f61a3974db42965efd57c7041d72c0542c09fec"
    file_path = "README.md"
    local = tmp_path / file_path
    local.write_text("nope\n", encoding="utf-8")

    with (
        mock.patch.object(mod, "inspect", return_value=_api_commit_report(expected)),
        mock.patch.object(mod, "_source_worktree_path", return_value=tmp_path),
        mock.patch.object(mod, "_mr_diff_paths", return_value={file_path}),
    ):
        result = mod.commit_worktree_files(
            "gitlab-org/gitlab",
            256812,
            expected_sha=expected,
            files=[file_path],
            apply=False,
        )

    assert result["ok"] is False
    assert result["error"] == "file_prefix_not_allowlisted"


def test_commit_worktree_files_apply_posts_source_commit_and_verifies_new_sha(tmp_path: Path) -> None:
    expected = "5f61a3974db42965efd57c7041d72c0542c09fec"
    new_sha = "d7591e8fdbd91234567890123456789012345678"
    file_path = "spec/requests/api/mcp/handlers/list_tools_spec.rb"
    local = tmp_path / file_path
    local.parent.mkdir(parents=True)
    local.write_text("spec content\n", encoding="utf-8")

    before = _api_commit_report(expected)
    after = _api_commit_report(new_sha)
    with (
        mock.patch.object(mod, "inspect", side_effect=[before, after]),
        mock.patch.object(mod, "_source_worktree_path", return_value=tmp_path),
        mock.patch.object(mod, "_mr_diff_paths", return_value={file_path}),
        mock.patch.object(mod, "_raw_mr", return_value={"ok": True, "data": {"sha": expected}}),
        mock.patch.object(
            mod.gl,
            "_request",
            return_value={"ok": True, "status": 201, "data": {"id": new_sha, "short_id": new_sha[:8]}},
        ) as request,
    ):
        result = mod.commit_worktree_files(
            "gitlab-org/gitlab",
            256812,
            expected_sha=expected,
            files=[file_path],
            apply=True,
        )

    assert result["ok"] is True
    assert result["applied"] is True
    assert result["sha_changed"] is True
    assert result["new_sha"] == new_sha
    request.assert_called_once()
    assert request.call_args.args[0] == "POST"
    assert request.call_args.args[1] == "/projects/gitlab-community%2Fgitlab-org%2Fgitlab/repository/commits"
    payload = request.call_args.kwargs["payload"]
    assert payload["branch"] == "chatgpt/630107-mcp-protocol-events-v2"
    assert payload["actions"][0]["file_path"] == file_path
    assert payload["actions"][0]["content"] == "spec content\n"
