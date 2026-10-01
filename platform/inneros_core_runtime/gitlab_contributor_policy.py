"""GitLab ContributorOps — upstream read-only + authenticated write fork resolution."""

from __future__ import annotations

from typing import Any

UPSTREAM_PROJECT = "gitlab-org/gitlab"
UPSTREAM_GIT_URL = "https://gitlab.com/gitlab-org/gitlab.git"
UPSTREAM_DEFAULT_BRANCH = "master"

# Prefer personal fork when present; community fork is the live write target for @rafagye today.
WRITE_FORK_CANDIDATES: tuple[str, ...] = (
    "rafagye/gitlab",
    "gitlab-community/gitlab-org/gitlab",
)

LOGICAL_REPO_ALIASES: dict[str, str] = {
    UPSTREAM_PROJECT: "gitlab-community/gitlab-org/gitlab",
}

CONTRIBUTOR_POLICY_REPOS: frozenset[str] = frozenset(
    {
        UPSTREAM_PROJECT,
        *WRITE_FORK_CANDIDATES,
        "gitlab-community/gitlab-org/gitlab-runner",
        "rafagye/gitlab-runner",
    }
)


def canonical_contributor_repo(repo: str) -> str:
    item = (repo or "").strip()
    return LOGICAL_REPO_ALIASES.get(item, item)


def is_contributor_policy_repo(repo: str) -> bool:
    return (repo or "").strip() in CONTRIBUTOR_POLICY_REPOS or (repo or "").strip() in LOGICAL_REPO_ALIASES


def _push_evidence_via_merge_requests(project_path: str, username: str) -> dict[str, Any]:
    from inneros_core_runtime import local_gitlab_plane as gl

    encoded = gl.project_api_path(project_path)
    res = gl._request(
        "GET",
        f"/projects/{encoded}/merge_requests",
        query={"author_username": username, "state": "all", "per_page": 5},
        timeout=30,
    )
    rows = res.get("data") if res.get("ok") and isinstance(res.get("data"), list) else []
    hits = [row for row in rows if isinstance(row, dict)]
    return {
        "ok": bool(hits),
        "count": len(hits),
        "sample_iids": [row.get("iid") for row in hits[:3]],
        "source": "merge_request_authorship",
    }


def _member_access_level(project_path: str, user_id: int) -> dict[str, Any]:
    from inneros_core_runtime import local_gitlab_plane as gl

    encoded = gl.project_api_path(project_path)
    res = gl._request(
        "GET",
        f"/projects/{encoded}/members/all/{user_id}",
        timeout=30,
    )
    if not res.get("ok"):
        return {"ok": False, "project": project_path, "error": "member_lookup_failed", "detail": res}
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    level = int(data.get("access_level") or 0)
    return {
        "ok": True,
        "project": project_path,
        "access_level": level,
        "can_push": level >= 30,
        "member": {
            "username": data.get("username"),
            "access_level": level,
        },
    }


def resolve_authenticated_write_fork(
    *,
    upstream: str = UPSTREAM_PROJECT,
    namespace: str = "rafagye",
) -> dict[str, Any]:
    """Pick the fork the authenticated token may push to for ContributorOps."""
    from inneros_core_runtime import local_gitlab_plane as gl

    if upstream != UPSTREAM_PROJECT:
        return {"ok": False, "error": "upstream_not_supported", "upstream": upstream}

    status = gl.gitlab_status()
    if not status.get("auth_ok"):
        return {"ok": False, "error": "gitlab_auth_not_ready", "status": status}

    verified = status.get("verified_user") or {}
    username = str(verified.get("username") or "").strip()
    user_id = verified.get("id")
    if not username or not user_id:
        return {"ok": False, "error": "verified_user_missing", "status": status}

    if namespace and username != namespace:
        return {
            "ok": False,
            "error": "authenticated_namespace_mismatch",
            "expected_namespace": namespace,
            "actual_username": username,
        }

    upstream_summary = gl.project_summary(UPSTREAM_PROJECT)
    upstream_id = (upstream_summary.get("project") or {}).get("id") if upstream_summary.get("ok") else None

    candidates: list[dict[str, Any]] = []
    for project_path in WRITE_FORK_CANDIDATES:
        summary = gl.project_summary(project_path)
        row: dict[str, Any] = {
            "project_path": project_path,
            "project_ok": bool(summary.get("ok")),
            "web_url": (summary.get("project") or {}).get("web_url"),
            "default_branch": (summary.get("project") or {}).get("default_branch"),
        }
        if not summary.get("ok"):
            row["reject_reason"] = "project_not_visible"
            candidates.append(row)
            continue
        project = summary.get("project") or {}
        fork_parent = project.get("forked_from_project_id")
        row["forked_from_project_id"] = fork_parent
        row["upstream_match"] = bool(upstream_id and fork_parent and int(fork_parent) == int(upstream_id))
        access = _member_access_level(project_path, int(user_id))
        row["access"] = access
        can_push = bool(access.get("ok") and access.get("can_push"))
        if not can_push:
            evidence = _push_evidence_via_merge_requests(project_path, username)
            row["push_evidence"] = evidence
            can_push = bool(evidence.get("ok"))
        row["can_push"] = can_push
        candidates.append(row)

    chosen = next((c for c in candidates if c.get("can_push")), None)
    if not chosen:
        return {
            "ok": False,
            "error": "write_fork_not_found",
            "upstream": UPSTREAM_PROJECT,
            "authenticated_user": username,
            "candidates": candidates,
        }

    git_url = f"https://gitlab.com/{chosen['project_path']}.git"
    return {
        "ok": True,
        "upstream_project": UPSTREAM_PROJECT,
        "upstream_git_url": UPSTREAM_GIT_URL,
        "upstream_default_branch": UPSTREAM_DEFAULT_BRANCH,
        "write_fork_project": chosen["project_path"],
        "write_fork_git_url": git_url,
        "write_fork_default_branch": chosen.get("default_branch") or UPSTREAM_DEFAULT_BRANCH,
        "authenticated_user": username,
        "push_remote": "origin",
        "fetch_upstream_remote": "upstream",
        "candidates": candidates,
        "policy": {
            "upstream": "read_fetch_only",
            "write_fork": "push_and_commits_only",
            "deny_force_push": True,
            "deny_protected_branch_writes": True,
        },
    }


def issue_work_duplicate_check(project: str, issue_iid: int, *, author_username: str = "rafagye") -> dict[str, Any]:
    """Return whether the authenticated contributor already has open MR work on this issue."""
    from inneros_core_runtime import local_gitlab_plane as gl

    if project != UPSTREAM_PROJECT:
        return {"ok": False, "error": "project_not_supported", "project": project}

    issue = gl.get_issue(project, int(issue_iid))
    if not issue.get("ok"):
        return issue

    related = gl._request("GET", f"/projects/{gl.project_api_path(project)}/issues/{int(issue_iid)}/related_merge_requests")
    related_rows = related.get("data") if related.get("ok") and isinstance(related.get("data"), list) else []

    opened_by_author: list[dict[str, Any]] = []
    for mr in related_rows:
        if not isinstance(mr, dict):
            continue
        author = str((mr.get("author") or {}).get("username") or "")
        if author == author_username and mr.get("state") == "opened":
            opened_by_author.append(
                {
                    "iid": mr.get("iid"),
                    "title": mr.get("title"),
                    "source_branch": mr.get("source_branch"),
                    "web_url": mr.get("web_url"),
                }
            )

    branch_tokens = [str(issue_iid)]
    title_lower = str((issue.get("issue") or {}).get("title") or "").lower()
    search = gl._request(
        "GET",
        f"/projects/{gl.project_api_path(project)}/merge_requests",
        query={"author_username": author_username, "state": "opened", "per_page": 50},
    )
    search_rows = search.get("data") if search.get("ok") and isinstance(search.get("data"), list) else []
    heuristic_hits: list[dict[str, Any]] = []
    for mr in search_rows:
        if not isinstance(mr, dict):
            continue
        branch = str(mr.get("source_branch") or "")
        title = str(mr.get("title") or "")
        if any(token in branch for token in branch_tokens) or str(issue_iid) in title:
            heuristic_hits.append(
                {
                    "iid": mr.get("iid"),
                    "title": title,
                    "source_branch": branch,
                    "web_url": mr.get("web_url"),
                }
            )

    duplicate = bool(opened_by_author or heuristic_hits)
    return {
        "ok": True,
        "project": project,
        "issue_iid": int(issue_iid),
        "issue": issue.get("issue"),
        "author_username": author_username,
        "duplicate_open_work": duplicate,
        "related_open_mrs_by_author": opened_by_author,
        "heuristic_open_mrs_by_author": heuristic_hits,
        "safe_to_start_new_branch": not duplicate,
    }


def contributorops_preflight(
    *,
    issue_iid: int | None = None,
    namespace: str = "rafagye",
) -> dict[str, Any]:
    """Glab + API identity, fork resolution, optional issue duplicate guard."""
    from inneros_core_runtime import local_gitlab_plane as gl

    status = gl.gitlab_status()
    glab = status.get("glab") or {}
    fork = resolve_authenticated_write_fork(namespace=namespace)
    remote_policy = {
        "upstream": UPSTREAM_GIT_URL,
        "origin": fork.get("write_fork_git_url") if fork.get("ok") else None,
    }
    out: dict[str, Any] = {
        "ok": bool(status.get("auth_ok") and fork.get("ok")),
        "correlation_hint": "gitlab-contributorops-repair-20261001",
        "gitlab_auth_ok": bool(status.get("auth_ok")),
        "verified_user": status.get("verified_user"),
        "glab_available": bool(glab.get("glab_available")),
        "glab_path": glab.get("glab_path"),
        "glab_token_present": bool(glab.get("token_present")),
        "api_token_present": bool(status.get("token_present")),
        "note_glab": (
            "REST API via owner_vault is authoritative; export GITLAB_TOKEN from vault for glab CLI parity."
            if not glab.get("token_present")
            else None
        ),
        "fork_resolution": fork,
        "remote_policy": remote_policy,
    }
    if issue_iid is not None:
        out["issue_guard"] = issue_work_duplicate_check(UPSTREAM_PROJECT, int(issue_iid))
        if out["issue_guard"].get("duplicate_open_work"):
            out["ok"] = False
            out["error"] = "duplicate_work_on_issue"
    return out
