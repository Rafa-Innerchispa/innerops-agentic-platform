"""GitLab read surfaces via capability_gateway (chatgpt_compact stays at 25 tools)."""

from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import capability_gateway as cg
from inneros_core_runtime import capability_gateway_lep as cgl
from inneros_core_runtime import capability_router as cr
from inneros_core_runtime import mcp_profiles as mp


def test_gitlab_read_capabilities_registered_and_searchable():
    cgl.register_local_execution_capabilities()
    search = cg.capability_search("gitlab", max_results=20)
    assert search["ok"] is True
    ids = {row["capability_id"] for row in search["capabilities"]}
    assert "local_gitlab.get_merge_request.v1" in ids
    assert "local_gitlab.list_merge_request_discussions.v1" in ids
    assert "local_gitlab.list_merge_request_pipelines.v1" in ids
    assert len(ids) >= 5

    describe = cg.capability_describe("local_gitlab.get_merge_request.v1")
    assert describe["ok"] is True
    assert describe["capability"]["mode"] == "read_only"

    alias = cg.capability_describe("local_gitlab_get_merge_request")
    assert alias["ok"] is True


def test_route_mcp_tools_recommends_gitlab_capabilities():
    routed = cr.route_tools(
        title="Inspect GitLab MR read feedback CI gitlab-org/gitlab !257991",
        granted_scopes=["ralfia:read", "ralfia:agents"],
    )
    assert routed["ok"] is True
    rec = {row["capability_id"] for row in routed["recommended_capabilities"]}
    assert "local_gitlab.get_merge_request.v1" in rec

    compact = mp.get_profile("chatgpt_compact")
    assert len(compact["tools"]) == 25


def _approved_gitlab_mr(**changes):
    head = "b62d6cabf2d74fbdef10817109eb6d25ae2b5cf6"
    data = {
        "state": "opened",
        "sha": head,
        "source_branch": "chatgpt/607885-versioned-method-naming",
        "target_branch": "master",
        "source_project_id": 112233,
        "rebase_in_progress": False,
    }
    data.update(changes)
    return data


def _approved_fork():
    return {"ok": True, "project": {"id": 112233}}


def test_guarded_gitlab_rebase_is_high_risk_and_requires_sha():
    cgl.register_local_execution_capabilities()
    m = cg.capability_describe("local_gitlab.rebase_reviewed_merge_request.v1")
    assert m["ok"] is True
    spec = m["capability"]
    assert spec["mode"] == "mutation"
    assert spec["risk_class"] == "high"
    assert "ralfia:agents" in spec["required_scopes"]
    assert "expected_source_sha" in spec["parameters_schema"]["required"]


def test_guarded_gitlab_rebase_rejects_other_merge_requests_before_api():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with mock.patch.object(gl, "_request") as request:
        result = gl.rebase_reviewed_merge_request(
            "gitlab-org/gitlab", 257991,
            "b62d6cabf2d74fbdef10817109eb6d25ae2b5cf6",
            dry_run=False,
        )
    assert result["error"] == "rebase_mr_not_allowlisted"
    request.assert_not_called()


def test_guarded_gitlab_rebase_rejects_changed_sha_and_never_puts():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with (
        mock.patch.object(gl, "_request", return_value={
            "ok": True, "status": 200, "data": _approved_gitlab_mr(),
        }) as request,
        mock.patch.object(gl, "project_summary") as project_summary,
    ):
        result = gl.rebase_reviewed_merge_request(
            "gitlab-org/gitlab", 255760, "a" * 40, dry_run=False,
        )
    assert result["error"] == "rebase_source_sha_changed"
    assert result["observed_sha"].startswith("b62d6cab")
    assert request.call_count == 1
    project_summary.assert_not_called()


def test_guarded_gitlab_rebase_dry_run_verifies_identity_without_put():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with (
        mock.patch.object(gl, "_request", return_value={
            "ok": True, "status": 200, "data": _approved_gitlab_mr(),
        }) as request,
        mock.patch.object(gl, "project_summary", return_value=_approved_fork()),
    ):
        result = gl.rebase_reviewed_merge_request(
            "gitlab-org/gitlab", 255760,
            "b62d6cabf2d74fbdef10817109eb6d25ae2b5cf6",
        )
    assert result["ok"] and result["dry_run"]
    assert result["queued"] is False
    assert result["ci_skipped"] is False
    assert result["would_request"]["method"] == "PUT"
    assert request.call_count == 1
    assert request.call_args.kwargs["query"]["include_rebase_in_progress"] == "true"


def test_guarded_gitlab_rebase_queues_only_once_after_preflight():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with (
        mock.patch.object(gl, "_request", side_effect=[
            {"ok": True, "status": 200, "data": _approved_gitlab_mr()},
            {"ok": True, "status": 202, "data": {"rebase_in_progress": True}},
        ]) as request,
        mock.patch.object(gl, "project_summary", return_value=_approved_fork()),
    ):
        result = gl.rebase_reviewed_merge_request(
            "gitlab-org/gitlab", 255760,
            "b62d6cabf2d74fbdef10817109eb6d25ae2b5cf6",
            dry_run=False,
        )
    assert result["ok"] and result["queued"]
    assert result["status"] == "queued_unverified"
    assert result["ci_skipped"] is False
    assert request.call_count == 2
    assert request.call_args.args[0] == "PUT"
    assert request.call_args.args[1].endswith("/255760/rebase")
    assert request.call_args.kwargs.get("payload") is None


def test_guarded_gitlab_rebase_rejects_running_rebase_and_wrong_fork():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    for mr, expected_error in [
        (_approved_gitlab_mr(rebase_in_progress=True), "rebase_already_running"),
        (_approved_gitlab_mr(source_project_id=8899), "rebase_source_fork_mismatch"),
        (_approved_gitlab_mr(target_branch="main"), "rebase_branch_mismatch"),
    ]:
        with (
            mock.patch.object(gl, "_request", return_value={
                "ok": True, "status": 200, "data": mr,
            }) as request,
            mock.patch.object(gl, "project_summary", return_value=_approved_fork()),
        ):
            result = gl.rebase_reviewed_merge_request(
                "gitlab-org/gitlab", 255760,
                "b62d6cabf2d74fbdef10817109eb6d25ae2b5cf6",
                dry_run=False,
            )
        assert result["error"] == expected_error
        assert request.call_count == 1


def test_guarded_gitlab_rebase_rejects_gitlab_failure_without_false_success():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with (
        mock.patch.object(gl, "_request", side_effect=[
            {"ok": True, "status": 200, "data": _approved_gitlab_mr()},
            {"ok": False, "status": 403, "error": "permission_denied"},
        ]),
        mock.patch.object(gl, "project_summary", return_value=_approved_fork()),
    ):
        result = gl.rebase_reviewed_merge_request(
            "gitlab-org/gitlab", 255760,
            "b62d6cabf2d74fbdef10817109eb6d25ae2b5cf6",
            dry_run=False,
        )
    assert result == {"ok": False, "error": "rebase_not_queued", "status": 403}


def test_get_merge_request_exposes_rebase_status_for_async_polling():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    mr = _approved_gitlab_mr(rebase_in_progress=True, merge_error="Rebase failed")
    with mock.patch.object(gl, "_request", return_value={
        "ok": True, "data": mr,
    }) as request:
        result = gl.get_merge_request("gitlab-org/gitlab", 255760)
    assert result["ok"] is True
    assert result["merge_request"]["rebase_in_progress"] is True
    assert result["merge_request"]["merge_error"] == "Rebase failed"
    assert request.call_args.kwargs["query"]["include_rebase_in_progress"] == "true"


def test_conflict_reader_is_registered_as_read_only_and_sha_scoped():
    cgl.register_local_execution_capabilities()
    result = cg.capability_describe(
        "local_gitlab.get_reviewed_merge_request_conflicts.v1"
    )
    assert result["ok"] is True
    manifest = result["capability"]
    assert manifest["mode"] == "read_only"
    assert "expected_source_sha" in manifest["parameters_schema"]["required"]


def test_conflict_reader_rejects_other_mrs_without_network():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with mock.patch.object(gl, "get_merge_request") as get_mr:
        result = gl.get_reviewed_merge_request_conflicts(
            "gitlab-org/gitlab", 257991, "b" * 40,
        )
    assert result["error"] == "conflicts_mr_not_allowlisted"
    get_mr.assert_not_called()


def test_conflict_reader_rejects_changed_source_without_graphql():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with (
        mock.patch.object(gl, "get_merge_request", return_value={
            "ok": True, "merge_request": {"sha": "b" * 40, "state": "opened"},
        }),
        mock.patch.object(gl.urllib.request, "urlopen") as http,
    ):
        result = gl.get_reviewed_merge_request_conflicts(
            "gitlab-org/gitlab", 255760, "c" * 40
        )
    assert result["error"] == "conflicts_source_sha_changed"
    http.assert_not_called()


def test_conflict_reader_returns_bounded_markers_and_expected_paths():
    from unittest import mock
    import json
    from inneros_core_runtime import local_gitlab_plane as gl
    expected_sha = "b" * 40
    conflict_text = (
        "<<<<<<< HEAD\\nour source\\n=======\\ntheir master\\n>>>>>>> master"
    )
    payload = json.dumps({"data": {"project": {"mergeRequest": {
        "diffHeadSha": expected_sha,
        "conflictStatus": "HAS_CONFLICTS",
        "conflicts": True,
        "conflictFiles": [{
            "ourPath": "doc/development/duo_agent_platform/mcp/graphql_integration.md",
            "theirPath": "doc/development/duo_agent_platform/mcp/graphql_integration.md",
            "content": conflict_text,
        }],
    }}}}).encode("utf-8")
    response = mock.MagicMock()
    response.status = 200
    response.read.return_value = payload
    with (
        mock.patch.object(gl, "get_merge_request", return_value={
            "ok": True, "merge_request": {"sha": expected_sha, "state": "opened"},
        }),
        mock.patch.object(gl, "_token", return_value=("secret-unprinted", "test")),
        mock.patch.object(gl.urllib.request, "urlopen") as http,
    ):
        http.return_value.__enter__.return_value = response
        result = gl.get_reviewed_merge_request_conflicts(
            "gitlab-org/gitlab", 255760, expected_sha
        )
    assert result["ok"] and result["files_available"]
    assert result["files_count"] == 1
    assert result["files"][0]["content"] == conflict_text
    assert result["files"][0]["our_path"].startswith("doc/development")
    request = http.call_args.args[0]
    assert request.full_url == "https://gitlab.com/api/graphql"
    assert request.get_method() == "POST"
    assert "secret-unprinted" not in json.dumps(result)


def test_conflict_reader_handles_missing_access_or_graphql_schema():
    from unittest import mock
    import json
    from inneros_core_runtime import local_gitlab_plane as gl
    expected_sha = "a" * 40
    initial = {"ok": True, "merge_request": {"sha": expected_sha, "state": "opened"}}
    with (
        mock.patch.object(gl, "get_merge_request", return_value=initial),
        mock.patch.object(gl, "_token", return_value=("", "missing")),
    ):
        denied = gl.get_reviewed_merge_request_conflicts(
            "gitlab-org/gitlab", 255760, expected_sha
        )
    assert denied["error"] == "gitlab_token_missing"
    response = mock.MagicMock()
    response.status = 200
    response.read.return_value = json.dumps({
        "errors": [{"message": "Cannot query field conflictFiles on MergeRequest"}],
    }).encode("utf-8")
    with (
        mock.patch.object(gl, "get_merge_request", return_value=initial),
        mock.patch.object(gl, "_token", return_value=("secret", "test")),
        mock.patch.object(gl.urllib.request, "urlopen") as http,
    ):
        http.return_value.__enter__.return_value = response
        invalid = gl.get_reviewed_merge_request_conflicts(
            "gitlab-org/gitlab", 255760, expected_sha
        )
    assert invalid["error"] == "graphql_schema_or_permission_error"
    assert invalid["error_count"] == 1


def test_conflict_reader_reports_unavailable_files_without_false_success():
    from unittest import mock
    import json
    from inneros_core_runtime import local_gitlab_plane as gl
    expected_sha = "a" * 40
    response = mock.MagicMock()
    response.status = 200
    response.read.return_value = json.dumps({"data": {"project": {
        "mergeRequest": {
            "diffHeadSha": expected_sha,
            "conflicts": True,
            "conflictStatus": "NO_PUSH_ACCESS",
            "conflictFiles": None,
        },
    }}}).encode("utf-8")
    with (
        mock.patch.object(gl, "get_merge_request", return_value={
            "ok": True, "merge_request": {"sha": expected_sha, "state": "opened"},
        }),
        mock.patch.object(gl, "_token", return_value=("token", "test")),
        mock.patch.object(gl.urllib.request, "urlopen") as http,
    ):
        http.return_value.__enter__.return_value = response
        result = gl.get_reviewed_merge_request_conflicts(
            "gitlab-org/gitlab", 255760, expected_sha
        )
    assert result["ok"] is True
    assert result["files_available"] is False
    assert result["conflict_status"] == "NO_PUSH_ACCESS"
    assert result["has_conflicts"] is True



def test_conflict_reader_requests_mergeability_recheck_on_list_endpoint():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    head = "b62d6cabf2d74fbdef10817109eb6d25ae2b5cf6"
    full = _approved_gitlab_mr()
    with mock.patch.object(gl, "_request", side_effect=[
        {"ok": True, "data": [{"iid": 255760}]},
        {"ok": True, "data": full},
    ]) as req:
        result = gl.get_merge_request(
            "gitlab-org/gitlab", 255760, refresh_merge_status=True
        )
    assert result["ok"] is True
    assert result["merge_request"]["sha"] == head
    assert req.call_count == 2
    assert req.call_args_list[0].args[1].endswith("/merge_requests")
    assert req.call_args_list[0].kwargs["query"] == {
        "iids[]": 255760,
        "with_merge_status_recheck": "true",
        "per_page": 1,
    }
    assert req.call_args_list[1].args[1].endswith("/merge_requests/255760")


def test_recheck_rejects_nonallowlisted_merge_requests_and_invalid_rows():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with mock.patch.object(gl, "_request") as req:
        forbidden = gl.get_merge_request(
            "gitlab-org/gitlab", 257991, refresh_merge_status=True
        )
    assert forbidden["error"] == "merge_recheck_not_allowlisted"
    req.assert_not_called()
    with mock.patch.object(gl, "_request", return_value={
        "ok": True, "data": [{"iid": 42}]
    }) as req:
        malformed = gl.get_merge_request(
            "gitlab-org/gitlab", 255760, refresh_merge_status=True
        )
    assert malformed["error"] == "merge_recheck_mr_missing"
    assert req.call_count == 1


def test_recheck_denied_reports_unavailable_without_claiming_refreshed_status():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with mock.patch.object(gl, "_request", return_value={
        "ok": False, "status": 403,
    }) as req:
        result = gl.get_merge_request(
            "gitlab-org/gitlab", 255760, refresh_merge_status=True
        )
    assert result["error"] == "merge_recheck_list_unavailable"
    assert result["status"] == 403
    assert req.call_count == 1


def test_graphql_conflict_reader_calls_rechecked_gitlab_mr():
    from unittest import mock
    from inneros_core_runtime import local_gitlab_plane as gl
    with mock.patch.object(gl, "get_merge_request", return_value={
        "ok": True, "merge_request": {
            "state": "opened", "sha": "b" * 40
        }
    }) as get_mr, mock.patch.object(gl, "_token", return_value=("", "missing")):
        result = gl.get_reviewed_merge_request_conflicts(
            "gitlab-org/gitlab", 255760, "b" * 40
        )
    assert result["error"] == "gitlab_token_missing"
    get_mr.assert_called_once_with(
        "gitlab-org/gitlab", 255760, refresh_merge_status=True
    )
