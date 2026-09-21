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


def origin_branches(source: str) -> list[str]:
    res = gl._run(
        ["git", "-C", source, "for-each-ref", "--format=%(refname:strip=3)", "refs/remotes/origin"],
        timeout=30,
    )
    if not res.get("ok"):
        return []
    return sorted({
        line.strip()
        for line in str(res.get("stdout") or "").splitlines()
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

        refresh = gl._run(["git", "-C", source, "fetch", "origin", "--prune", "--tags"], timeout=180)
        branches = origin_branches(source)
        refspecs = [f"refs/remotes/origin/{b}:refs/heads/{b}" for b in branches]

        with gl._gitlab_git_auth_env() as env:
            if refspecs:
                branch_push = gl._run_with_env(
                    ["git", "-C", source, "push", "gitlab", *refspecs],
                    env,
                    timeout=900,
                )
            else:
                branch_push = {"ok": True, "returncode": 0, "stderr": ""}

            branch_results = []
            if not branch_push.get("ok"):
                # Diagnose safely and allow independent fast-forward branches to succeed.
                for branch in branches:
                    pushed = gl._run_with_env(
                        ["git", "-C", source, "push", "gitlab", f"refs/remotes/origin/{branch}:refs/heads/{branch}"],
                        env,
                        timeout=300,
                    )
                    branch_results.append({
                        "branch": branch,
                        "ok": bool(pushed.get("ok")),
                        "returncode": pushed.get("returncode"),
                        "stderr": gl._redact(str(pushed.get("stderr") or ""))[:1000],
                    })

            tags = gl._run_with_env(
                ["git", "-C", source, "push", "gitlab", "--tags"],
                env,
                timeout=600,
            )

        branches_ok = bool(branch_push.get("ok")) or all(item["ok"] for item in branch_results)
        row = {
            "github": action.get("github"),
            "target": target,
            "refresh_ok": bool(refresh.get("ok")),
            "branches_ok": branches_ok,
            "branch_count": len(branches),
            "batch_branch_push_ok": bool(branch_push.get("ok")),
            "branch_results": branch_results,
            "tags_ok": bool(tags.get("ok")),
            "visibility_sync": action.get("visibility_sync"),
        }
        rows.append(row)
        if not row["branches_ok"] or not row["tags_ok"]:
            failures.append(row)

    payload = {
        "ok": bool(inventory.get("ok")) and not failures,
        "timestamp": now(),
        "count": len(rows),
        "rows": rows,
        "failures": failures,
        "policy": "GitHub origin branches -> same GitLab branches, excluding origin/HEAD; non-force. Batch push with bounded conflict fallback. Local-only heads remain in local bare mirrors.",
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
