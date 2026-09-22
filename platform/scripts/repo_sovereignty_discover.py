#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

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

        # Owner-approved explicit promotion policy.
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
                # Local copy remains valid even if upstream refresh fails.
                failures.append({"repo": full, "stage": "local_mirror_refresh", "detail": refresh})

        fsck = run(["git", "--git-dir", str(mirror), "fsck", "--full", "--no-dangling"], timeout=300)

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

        # Push committed refs safely from the bare local mirror.
        push_ok = False
        if glp.project_summary(target).get("ok"):
            gitlab_url = f"https://gitlab.com/{target}.git"
            current_url = run(["git", "--git-dir", str(mirror), "remote", "get-url", "gitlab"], timeout=20)
            if current_url.get("ok"):
                run(["git", "--git-dir", str(mirror), "remote", "set-url", "gitlab", gitlab_url], timeout=20)
            else:
                run(["git", "--git-dir", str(mirror), "remote", "add", "gitlab", gitlab_url], timeout=20)

            with glp._gitlab_git_auth_env() as env:
                branches = glp._run_with_env(["git", "--git-dir", str(mirror), "push", "gitlab", "--all"], env, timeout=600)
                tags = glp._run_with_env(["git", "--git-dir", str(mirror), "push", "gitlab", "--tags"], env, timeout=600)
            push_ok = bool(branches.get("ok")) and bool(tags.get("ok"))
            if not push_ok:
                failures.append({"repo": full, "stage": "gitlab_push", "target": target})

        verified = glp.project_summary(target)
        verified_visibility = (verified.get("project") or {}).get("visibility") if verified.get("ok") else None

        rows.append({
            "repo": full,
            "github_visibility": desired_visibility,
            "gitlab_target": target,
            "gitlab_visibility": verified_visibility,
            "mirror": str(mirror),
            "mirror_fsck_ok": bool(fsck.get("ok")),
            "gitlab_push_ok": push_ok,
            "created_gitlab": created,
            "ok": bool(fsck.get("ok")) and verified_visibility == desired_visibility,
        })

    payload = {
        "ok": not failures,
        "timestamp": now(),
        "owner": OWNER,
        "count": len(rows),
        "rows": rows,
        "failures": failures,
        "policy": policy,
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
