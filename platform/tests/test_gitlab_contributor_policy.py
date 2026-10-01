"""GitLab ContributorOps policy — fork resolution and scope (mocked + optional live)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import gitlab_contributor_policy as gcp
from inneros_core_runtime import local_execution_plane as lep


def test_dev_swarm_scope_accepts_gitlab_org_gitlab():
    with patch.object(gcp, "resolve_authenticated_write_fork", return_value={"ok": True, "write_fork_git_url": "https://gitlab.com/gitlab-community/gitlab-org/gitlab.git"}):
        status = lep.dev_swarm_scope_status(repo="gitlab-org/gitlab")
    assert status["ok"] is True
    assert status["policy"]["repo"] == "gitlab-org/gitlab"
    assert status["policy"]["policy"].get("contributor_ops") is True


def test_upstream_push_forbidden_on_contributor_repo():
    policy = lep._remote_policy("gitlab-org/gitlab")
    assert policy.get("upstream", "").endswith("gitlab-org/gitlab.git")
    assert "gitlab-community" in policy.get("origin", "")


def test_resolve_write_fork_picks_push_capable_candidate():
    fake_status = {"auth_ok": True, "verified_user": {"id": 1, "username": "rafagye"}}
    with (
        patch("inneros_core_runtime.local_gitlab_plane.gitlab_status", return_value=fake_status),
        patch("inneros_core_runtime.local_gitlab_plane.project_summary", side_effect=lambda p: {"ok": p == "gitlab-community/gitlab-org/gitlab", "project": {"id": 9, "default_branch": "master"}}),
        patch.object(gcp, "_member_access_level", return_value={"ok": False}),
        patch.object(gcp, "_push_evidence_via_merge_requests", return_value={"ok": True, "count": 1}),
    ):
        out = gcp.resolve_authenticated_write_fork()
    assert out["ok"] is True
    assert out["write_fork_project"] == "gitlab-community/gitlab-org/gitlab"


def test_issue_duplicate_guard_detects_author_related_mr():
    issue_payload = {"ok": True, "issue": {"iid": 631702, "title": "Example", "state": "opened"}}
    related = {
        "ok": True,
        "data": [
            {
                "iid": 99,
                "state": "opened",
                "author": {"username": "rafagye"},
                "source_branch": "chatgpt/631702-fix",
                "title": "Fix",
                "web_url": "https://gitlab.com/example",
            }
        ],
    }
    with (
        patch("inneros_core_runtime.local_gitlab_plane.get_issue", return_value=issue_payload),
        patch("inneros_core_runtime.local_gitlab_plane._request", side_effect=[related, {"ok": True, "data": []}]),
    ):
        guard = gcp.issue_work_duplicate_check("gitlab-org/gitlab", 631702, author_username="rafagye")
    assert guard["ok"] is True
    assert guard["duplicate_open_work"] is True
    assert guard["safe_to_start_new_branch"] is False


@pytest.mark.skipif(os.getenv("GITLAB_E2E_LIVE") != "1", reason="set GITLAB_E2E_LIVE=1 for live fork/issue checks")
def test_live_issue_631702_no_duplicate_for_rafagye():
    guard = gcp.issue_work_duplicate_check("gitlab-org/gitlab", 631702, author_username="rafagye")
    assert guard["ok"] is True
    assert guard["duplicate_open_work"] is False
