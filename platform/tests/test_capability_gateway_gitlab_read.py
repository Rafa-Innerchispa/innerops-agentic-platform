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
