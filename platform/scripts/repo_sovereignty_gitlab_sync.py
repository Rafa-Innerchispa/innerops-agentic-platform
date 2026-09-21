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
        with gl._gitlab_git_auth_env() as env:
            branches = gl._run_with_env(
                [
                    "git",
                    "-C",
                    source,
                    "push",
                    "gitlab",
                    "refs/remotes/origin/*:refs/heads/*",
                ],
                env,
                timeout=600,
            )
            tags = gl._run_with_env(
                ["git", "-C", source, "push", "gitlab", "--tags"],
                env,
                timeout=600,
            )

        row = {
            "github": action.get("github"),
            "target": target,
            "refresh_ok": bool(refresh.get("ok")),
            "branches_ok": bool(branches.get("ok")),
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
        "policy": "GitHub origin refs -> GitLab heads, non-force; local-only committed heads are preserved in the local bare mirror.",
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
