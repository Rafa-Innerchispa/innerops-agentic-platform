#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from inneros_core_runtime import local_gitlab_plane as gl

STATE_ROOT = Path("/home/rlopez/inneros/inneros_core/var/repo_sovereignty")
STATUS_PATH = STATE_ROOT / "gitlab-sync.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(source: str, argv: list[str], timeout: int = 30) -> dict:
    return gl._run(["git", "-C", source, *argv], timeout=timeout)


def rev(source: str, ref: str) -> str:
    r = run(source, ["rev-parse", "--verify", ref], timeout=15)
    return str(r.get("stdout") or "").strip() if r.get("ok") else ""


def is_ancestor(source: str, older: str, newer: str) -> bool:
    if not older or not newer:
        return False
    return bool(run(source, ["merge-base", "--is-ancestor", older, newer], timeout=20).get("ok"))


def origin_branches(source: str) -> list[str]:
    r = run(
        source,
        ["for-each-ref", "--format=%(refname:strip=3)", "refs/remotes/origin"],
        timeout=30,
    )
    if not r.get("ok"):
        return []
    return sorted({
        line.strip()
        for line in str(r.get("stdout") or "").splitlines()
        if line.strip() and line.strip() != "HEAD"
    })


def main() -> int:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    inventory = gl.prepare_github_mirrors(
        namespace="rafagye",
        create_missing=True,
        configure_remotes=True,
        push=False,
        dry_run=False,
    )
    rows = []
    failures = []

    for action in inventory.get("actions") or []:
        source = str(action.get("source_path") or "")
        target = str(action.get("target") or "")
        if not source or not target or not action.get("project_exists_or_created"):
            continue

        refresh_origin = run(source, ["fetch", "origin", "--prune", "--tags"], timeout=180)

        with gl._gitlab_git_auth_env() as env:
            refresh_gitlab = gl._run_with_env(
                ["git", "-C", source, "fetch", "gitlab", "--prune"],
                env,
                timeout=300,
            )

            branch_results = []
            for branch in origin_branches(source):
                origin_ref = f"refs/remotes/origin/{branch}"
                gitlab_ref = f"refs/remotes/gitlab/{branch}"
                origin_sha = rev(source, origin_ref)
                gitlab_sha = rev(source, gitlab_ref)

                if not origin_sha:
                    branch_results.append({"branch": branch, "ok": False, "state": "origin_ref_missing"})
                    continue

                if origin_sha == gitlab_sha:
                    branch_results.append({"branch": branch, "ok": True, "state": "equal", "sha": origin_sha})
                    continue

                if not gitlab_sha:
                    push = gl._run_with_env(
                        ["git", "-C", source, "push", "gitlab", f"{origin_ref}:refs/heads/{branch}"],
                        env,
                        timeout=300,
                    )
                    branch_results.append({
                        "branch": branch,
                        "ok": bool(push.get("ok")),
                        "state": "created" if push.get("ok") else "create_failed",
                        "origin_sha": origin_sha,
                        "stderr": gl._redact(str(push.get("stderr") or ""))[:800],
                    })
                    continue

                if is_ancestor(source, gitlab_sha, origin_sha):
                    push = gl._run_with_env(
                        ["git", "-C", source, "push", "gitlab", f"{origin_ref}:refs/heads/{branch}"],
                        env,
                        timeout=300,
                    )
                    branch_results.append({
                        "branch": branch,
                        "ok": bool(push.get("ok")),
                        "state": "fast_forwarded" if push.get("ok") else "fast_forward_failed",
                        "origin_sha": origin_sha,
                        "previous_gitlab_sha": gitlab_sha,
                        "stderr": gl._redact(str(push.get("stderr") or ""))[:800],
                    })
                    continue

                if is_ancestor(source, origin_sha, gitlab_sha):
                    branch_results.append({
                        "branch": branch,
                        "ok": True,
                        "state": "gitlab_ahead_preserved",
                        "origin_sha": origin_sha,
                        "gitlab_sha": gitlab_sha,
                    })
                    continue

                safe_branch = f"github-sync/{branch}"
                push = gl._run_with_env(
                    ["git", "-C", source, "push", "gitlab", f"{origin_ref}:refs/heads/{safe_branch}"],
                    env,
                    timeout=300,
                )
                branch_results.append({
                    "branch": branch,
                    "ok": bool(push.get("ok")),
                    "state": "diverged_preserved" if push.get("ok") else "divergence_preserve_failed",
                    "origin_sha": origin_sha,
                    "gitlab_sha": gitlab_sha,
                    "preserved_as": safe_branch,
                    "stderr": gl._redact(str(push.get("stderr") or ""))[:800],
                })

            tags = gl._run_with_env(
                ["git", "-C", source, "push", "gitlab", "--tags"],
                env,
                timeout=600,
            )

        branches_ok = all(item.get("ok") for item in branch_results)
        row = {
            "github": action.get("github"),
            "target": target,
            "origin_fetch_ok": bool(refresh_origin.get("ok")),
            "gitlab_fetch_ok": bool(refresh_gitlab.get("ok")),
            "branches_ok": branches_ok,
            "branch_count": len(branch_results),
            "branch_results": branch_results,
            "tags_ok": bool(tags.get("ok")),
            "visibility_sync": action.get("visibility_sync"),
        }
        rows.append(row)
        if not branches_ok or not row["tags_ok"] or not row["gitlab_fetch_ok"]:
            failures.append(row)

    payload = {
        "ok": bool(inventory.get("ok")) and not failures,
        "timestamp": now(),
        "count": len(rows),
        "rows": rows,
        "failures": failures,
        "policy": (
            "GitHub origin branches reconcile to GitLab without force. "
            "Equal/fast-forward refs sync in place; GitLab-ahead refs are preserved; "
            "true divergences preserve GitHub under github-sync/<branch>. "
            "Local-only heads remain in local bare mirrors."
        ),
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
