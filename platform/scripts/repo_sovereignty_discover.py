#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime import local_github_plane as ghp
from inneros_core_runtime import local_gitlab_plane as glp

OWNER = "Rafa-Innerchispa"
GITLAB_NAMESPACE = "rafagye"
ROOT = Path("/home/rlopez/inneros/inneros_core/var/repo_sovereignty")
MIRROR_ROOT = Path("/mnt/datos_agentes/backups/git_mirrors")
POLICY_PATH = Path("/home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform/platform/scripts/repo_publication_policy.json")
STATUS_PATH = ROOT / "account-discovery.json"


def run(argv: list[str], timeout: int = 300) -> dict:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    return {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_dir(mirror: Path, args: list[str], timeout: int = 60) -> dict:
    return run(["git", "--git-dir", str(mirror), *args], timeout=timeout)


def rev(mirror: Path, ref: str) -> str:
    result = git_dir(mirror, ["rev-parse", "--verify", ref], timeout=20)
    return str(result.get("stdout") or "").strip() if result.get("ok") else ""


def is_ancestor(mirror: Path, older: str, newer: str) -> bool:
    if not older or not newer:
        return False
    return bool(git_dir(mirror, ["merge-base", "--is-ancestor", older, newer], timeout=30).get("ok"))


def local_branches(mirror: Path) -> list[str]:
    result = git_dir(mirror, ["for-each-ref", "--format=%(refname:strip=2)", "refs/heads"], timeout=30)
    if not result.get("ok"):
        return []
    return sorted({line.strip() for line in str(result.get("stdout") or "").splitlines() if line.strip()})


def decide_branch_state(local_sha: str, gitlab_sha: str, gitlab_is_ancestor: bool, local_is_ancestor: bool) -> str:
    if not local_sha:
        return "source_missing"
    if not gitlab_sha:
        return "create"
    if local_sha == gitlab_sha:
        return "equal"
    if gitlab_is_ancestor:
        return "fast_forward"
    if local_is_ancestor:
        return "gitlab_ahead_preserved"
    return "diverged_preserved"


def reconcile_gitlab(mirror: Path, target: str) -> dict[str, Any]:
    gitlab_url = f"https://gitlab.com/{target}.git"
    current_url = git_dir(mirror, ["remote", "get-url", "gitlab"], timeout=20)
    if current_url.get("ok"):
        git_dir(mirror, ["remote", "set-url", "gitlab", gitlab_url], timeout=20)
    else:
        git_dir(mirror, ["remote", "add", "gitlab", gitlab_url], timeout=20)

    branch_results: list[dict[str, Any]] = []
    with glp._gitlab_git_auth_env() as env:
        refresh = glp._run_with_env(
            [
                "git", "--git-dir", str(mirror), "fetch", "gitlab",
                "--prune", "+refs/heads/*:refs/gitlab-snapshot/*",
            ],
            env,
            timeout=600,
        )
        if not refresh.get("ok"):
            return {
                "ok": False,
                "gitlab_fetch_ok": False,
                "branches_ok": False,
                "tags_ok": False,
                "branch_results": [],
                "error": "gitlab_fetch_failed",
                "stderr": glp._redact(str(refresh.get("stderr") or ""))[:1000],
            }

        for branch in local_branches(mirror):
            local_ref = f"refs/heads/{branch}"
            gitlab_ref = f"refs/gitlab-snapshot/{branch}"
            local_sha = rev(mirror, local_ref)
            gitlab_sha = rev(mirror, gitlab_ref)
            state = decide_branch_state(
                local_sha,
                gitlab_sha,
                is_ancestor(mirror, gitlab_sha, local_sha),
                is_ancestor(mirror, local_sha, gitlab_sha),
            )

            if state == "source_missing":
                branch_results.append({"branch": branch, "ok": False, "state": state})
                continue
            if state in {"equal", "gitlab_ahead_preserved"}:
                branch_results.append({
                    "branch": branch,
                    "ok": True,
                    "state": state,
                    "github_sha": local_sha,
                    "gitlab_sha": gitlab_sha,
                })
                continue

            destination = branch if state in {"create", "fast_forward"} else f"github-sync/{branch}"
            push = glp._run_with_env(
                [
                    "git", "--git-dir", str(mirror), "push", "gitlab",
                    f"{local_ref}:refs/heads/{destination}",
                ],
                env,
                timeout=600,
            )
            branch_results.append({
                "branch": branch,
                "ok": bool(push.get("ok")),
                "state": state if push.get("ok") else f"{state}_failed",
                "github_sha": local_sha,
                "gitlab_sha": gitlab_sha,
                "preserved_as": destination if state == "diverged_preserved" else None,
                "stderr": glp._redact(str(push.get("stderr") or ""))[:800],
            })

        tags = glp._run_with_env(
            ["git", "--git-dir", str(mirror), "push", "gitlab", "--tags"],
            env,
            timeout=600,
        )

    branches_ok = all(item.get("ok") for item in branch_results)
    return {
        "ok": branches_ok and bool(tags.get("ok")),
        "gitlab_fetch_ok": True,
        "branches_ok": branches_ok,
        "tags_ok": bool(tags.get("ok")),
        "branch_results": branch_results,
        "tags_stderr": glp._redact(str(tags.get("stderr") or ""))[:1000],
    }


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    MIRROR_ROOT.mkdir(parents=True, exist_ok=True)

    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    public_repos = set(policy.get("public_repos") or [])

    gh = ghp.shutil_which("gh")
    if not gh:
        STATUS_PATH.write_text(json.dumps({"ok": False, "error": "gh_unavailable", "timestamp": now()}, indent=2), encoding="utf-8")
        return 2

    listed = ghp._run([
        gh, "repo", "list", OWNER,
        "--limit", "1000",
        "--json", "name,nameWithOwner,isPrivate,url,defaultBranchRef",
    ], timeout=120)
    if not listed.get("ok"):
        STATUS_PATH.write_text(json.dumps({"ok": False, "error": "github_list_failed", "detail": listed, "timestamp": now()}, indent=2), encoding="utf-8")
        return 3

    repos = json.loads(listed.get("stdout") or "[]")
    rows = []
    failures = []

    for repo in repos:
        name = str(repo.get("name") or "").strip()
        full = str(repo.get("nameWithOwner") or f"{OWNER}/{name}")
        if not name:
            continue

        if name in public_repos and bool(repo.get("isPrivate")):
            edit = ghp._run([
                gh, "repo", "edit", full,
                "--visibility", "public",
                "--accept-visibility-change-consequences",
            ], timeout=120)
            if edit.get("ok"):
                repo["isPrivate"] = False
            else:
                failures.append({"repo": full, "stage": "github_visibility", "detail": edit})

        desired_visibility = "private" if bool(repo.get("isPrivate")) else "public"
        safe = full.replace("/", "__")
        mirror = MIRROR_ROOT / f"{safe}.git"

        if not mirror.exists():
            clone = ghp._run([gh, "repo", "clone", full, str(mirror), "--", "--mirror"], timeout=600)
            if not clone.get("ok"):
                failures.append({"repo": full, "stage": "local_mirror_clone", "detail": clone})
                rows.append({"repo": full, "visibility": desired_visibility, "mirror": str(mirror), "ok": False})
                continue
        else:
            refresh = run(["git", "--git-dir", str(mirror), "fetch", "--prune", "--tags", "origin"], timeout=300)
            if not refresh.get("ok"):
                failures.append({"repo": full, "stage": "local_mirror_refresh", "detail": refresh})

        fsck = run(["git", "--git-dir", str(mirror), "fsck", "--full", "--no-dangling"], timeout=300)
        if not fsck.get("ok"):
            failures.append({"repo": full, "stage": "local_mirror_fsck", "detail": fsck})

        target = f"{GITLAB_NAMESPACE}/{glp._gitlab_safe_project_path(name)}"
        project = glp.project_summary(target)
        created = False
        if not project.get("ok"):
            create = glp._request(
                "POST",
                "/projects",
                payload={
                    "name": name,
                    "path": glp._gitlab_safe_project_path(name),
                    "visibility": desired_visibility,
                    "initialize_with_readme": False,
                },
                timeout=60,
            )
            created = bool(create.get("ok"))
            if not created:
                failures.append({"repo": full, "stage": "gitlab_create", "target": target, "detail": {k:v for k,v in create.items() if k != "data"}})
        else:
            current = (project.get("project") or {}).get("visibility")
            if current != desired_visibility:
                changed = glp._request(
                    "PUT",
                    f"/projects/{glp.project_api_path(target)}",
                    payload={"visibility": desired_visibility},
                    timeout=30,
                )
                if not changed.get("ok"):
                    failures.append({"repo": full, "stage": "gitlab_visibility", "target": target, "desired": desired_visibility})

        sync = {"ok": False, "gitlab_fetch_ok": False, "branches_ok": False, "tags_ok": False, "branch_results": []}
        if glp.project_summary(target).get("ok"):
            sync = reconcile_gitlab(mirror, target)
            if not sync.get("ok"):
                failures.append({
                    "repo": full,
                    "stage": "gitlab_safe_sync",
                    "target": target,
                    "branches_ok": sync.get("branches_ok"),
                    "tags_ok": sync.get("tags_ok"),
                    "gitlab_fetch_ok": sync.get("gitlab_fetch_ok"),
                    "detail": sync.get("error") or sync.get("tags_stderr") or "",
                })

        verified = glp.project_summary(target)
        verified_visibility = (verified.get("project") or {}).get("visibility") if verified.get("ok") else None

        rows.append({
            "repo": full,
            "github_visibility": desired_visibility,
            "gitlab_target": target,
            "gitlab_visibility": verified_visibility,
            "mirror": str(mirror),
            "mirror_fsck_ok": bool(fsck.get("ok")),
            "gitlab_push_ok": bool(sync.get("ok")),
            "gitlab_fetch_ok": bool(sync.get("gitlab_fetch_ok")),
            "gitlab_branches_ok": bool(sync.get("branches_ok")),
            "gitlab_tags_ok": bool(sync.get("tags_ok")),
            "branch_results": sync.get("branch_results") or [],
            "created_gitlab": created,
            "ok": bool(fsck.get("ok")) and verified_visibility == desired_visibility and bool(sync.get("ok")),
        })

    payload = {
        "ok": not failures,
        "timestamp": now(),
        "owner": OWNER,
        "count": len(rows),
        "rows": rows,
        "failures": failures,
        "policy": policy,
        "sync_policy": (
            "Account-wide GitHub->GitLab reconciliation is non-destructive: equal no-op; "
            "missing branches create; GitLab-behind fast-forwards; GitLab-ahead is preserved; "
            "true divergence stores GitHub under github-sync/<branch>; no force push or branch deletion."
        ),
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
