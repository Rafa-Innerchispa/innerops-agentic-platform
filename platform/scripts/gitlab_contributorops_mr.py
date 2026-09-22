#!/usr/bin/env python3
"""Safely inspect and mark owner-authored GitLab community MRs ready for review.

The script never accepts or prints GitLab credentials. It imports the existing
InnerOS GitLab provider, which resolves the owner PAT server-side.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import local_gitlab_plane as gl  # noqa: E402

ALLOWED_TARGET_PROJECTS = {
    "gitlab-org/gitlab",
    "gitlab-org/gitlab-runner",
}
ALLOWED_SOURCE_PROJECTS = {
    "gitlab-community/gitlab-org/gitlab",
    "gitlab-community/gitlab-org/gitlab-runner",
    "rafagye/gitlab",
    "rafagye/gitlab-runner",
}
ALLOWED_BRANCH_RE = re.compile(r"^(?:chatgpt|codex|cursor|antigravity|gemini|local-agent)/[A-Za-z0-9._/-]+$")
DRAFT_PREFIX_RE = re.compile(r"^(?:draft\s*[:\-]|wip\s*[:\-])\s*", re.IGNORECASE)


def _safe_data(res: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in res.items() if k not in {"token_source"}}


def _raw_mr(project: str, mr_iid: int) -> dict[str, Any]:
    encoded = gl.project_api_path(project)
    res = gl._request("GET", f"/projects/{encoded}/merge_requests/{mr_iid}")
    if not res.get("ok"):
        return {"ok": False, "error": "merge_request_unavailable", "provider": _safe_data(res)}
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    return {"ok": True, "data": data}


def _project_path(project_id: Any) -> str:
    if not project_id:
        return ""
    res = gl.project_summary(str(project_id))
    if not res.get("ok"):
        return ""
    return str((res.get("project") or {}).get("path_with_namespace") or "")


def inspect(project: str, mr_iid: int) -> dict[str, Any]:
    if project not in ALLOWED_TARGET_PROJECTS:
        return {"ok": False, "error": "target_project_not_allowlisted", "project": project}

    status = gl.gitlab_status()
    if not status.get("auth_ok"):
        return {"ok": False, "error": "gitlab_auth_not_ready"}

    username = str((status.get("verified_user") or {}).get("username") or "")
    raw = _raw_mr(project, mr_iid)
    if not raw.get("ok"):
        return raw

    data = raw["data"]
    source_project = _project_path(data.get("source_project_id"))
    source_branch = str(data.get("source_branch") or "")
    author = str((data.get("author") or {}).get("username") or "")

    pipelines = gl.list_merge_request_pipelines(project, mr_iid, limit=20)
    pipeline_rows = pipelines.get("pipelines") if isinstance(pipelines.get("pipelines"), list) else []
    latest_pipeline = pipeline_rows[0] if pipeline_rows else None

    discussions = gl.list_merge_request_discussions(project, mr_iid, limit=100)
    unresolved: list[dict[str, Any]] = []
    if discussions.get("ok"):
        for discussion in discussions.get("discussions") or []:
            for note in discussion.get("notes") or []:
                if note.get("resolvable") and not note.get("resolved"):
                    unresolved.append({
                        "discussion_id": discussion.get("id"),
                        "note_id": note.get("id"),
                        "author": note.get("author"),
                        "body": str(note.get("body") or "")[:500],
                    })

    title = str(data.get("title") or "")
    draft = bool(data.get("draft") or data.get("work_in_progress") or DRAFT_PREFIX_RE.match(title))

    guards = {
        "authenticated_user_is_author": bool(username) and username == author,
        "source_project_allowlisted": source_project in ALLOWED_SOURCE_PROJECTS,
        "source_branch_allowlisted": bool(ALLOWED_BRANCH_RE.match(source_branch)),
        "latest_pipeline_success": bool(latest_pipeline) and latest_pipeline.get("status") == "success",
        "no_unresolved_discussions": not unresolved,
        "state_open": data.get("state") == "opened",
    }
    ready_to_mark = all(guards.values())

    return {
        "ok": True,
        "project": project,
        "mr_iid": mr_iid,
        "web_url": data.get("web_url"),
        "title": title,
        "draft": draft,
        "state": data.get("state"),
        "author": author,
        "authenticated_user": username,
        "source_project": source_project,
        "source_branch": source_branch,
        "target_branch": data.get("target_branch"),
        "sha": data.get("sha"),
        "labels": data.get("labels") or [],
        "milestone": (data.get("milestone") or {}).get("title") if isinstance(data.get("milestone"), dict) else None,
        "blocking_discussions_resolved": data.get("blocking_discussions_resolved"),
        "latest_pipeline": latest_pipeline,
        "unresolved_discussions": unresolved,
        "guards": guards,
        "ready_to_mark": ready_to_mark,
    }


def mark_ready(project: str, mr_iid: int, apply: bool = False) -> dict[str, Any]:
    report = inspect(project, mr_iid)
    if not report.get("ok"):
        return report
    if not report.get("ready_to_mark"):
        return {**report, "ok": False, "error": "ready_guards_failed", "applied": False}
    if not report.get("draft"):
        return {**report, "applied": False, "already_ready": True}

    new_title = DRAFT_PREFIX_RE.sub("", str(report.get("title") or "")).strip()
    if not new_title:
        return {**report, "ok": False, "error": "ready_title_empty", "applied": False}

    if not apply:
        return {
            **report,
            "dry_run": True,
            "applied": False,
            "would_update": {"title": new_title},
        }

    encoded = gl.project_api_path(project)
    updated = gl._request(
        "PUT",
        f"/projects/{encoded}/merge_requests/{mr_iid}",
        payload={"title": new_title},
        timeout=60,
    )
    if not updated.get("ok"):
        return {
            **report,
            "ok": False,
            "error": "mark_ready_failed",
            "applied": False,
            "provider": _safe_data(updated),
        }

    verify = inspect(project, mr_iid)
    return {
        **verify,
        "applied": True,
        "previous_title": report.get("title"),
        "new_title": new_title,
        "verified_ready": bool(verify.get("ok")) and not bool(verify.get("draft")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "mark-ready"])
    parser.add_argument("--project", required=True, choices=sorted(ALLOWED_TARGET_PROJECTS))
    parser.add_argument("--mr", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.mr <= 0:
        result = {"ok": False, "error": "mr_iid_invalid"}
    elif args.action == "inspect":
        result = inspect(args.project, args.mr)
    else:
        result = mark_ready(args.project, args.mr, apply=args.apply)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
