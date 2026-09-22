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
