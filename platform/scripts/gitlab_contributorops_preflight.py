#!/usr/bin/env python3
"""ContributorOps preflight: identity, fork, issue duplicate guard (no secrets printed)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import gitlab_contributor_policy as gcp  # noqa: E402
from inneros_core_runtime import local_execution_plane as lep  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", type=int, default=None, help="Upstream issue IID (e.g. 631702)")
    parser.add_argument("--namespace", default="rafagye")
    parser.add_argument("--repo", default=gcp.UPSTREAM_PROJECT, help="Logical repo for dev_swarm policy")
    args = parser.parse_args()

    preflight = gcp.contributorops_preflight(issue_iid=args.issue, namespace=args.namespace)
    scope = lep.dev_swarm_scope_status(repo=args.repo)
    result = {
        "ok": bool(preflight.get("ok") and scope.get("ok")),
        "preflight": preflight,
        "dev_swarm_scope": scope,
        "e2e_lane": [
            "issue (gitlab-org/gitlab)",
            "RACB lock repo:gitlab-org/gitlab",
            "local_exec_prepare_repo + upstream fetch",
            "local_exec_create_worktree on chatgpt/* branch",
            "local_exec_write_file / apply_patch under allowed_paths",
            "local_exec_run_command_allowlisted (ruby-tests-local-only)",
            "local_exec_commit_branch",
            "local_exec_push_branch remote=origin (never upstream)",
            "local_gitlab_plane.create_draft_merge_request -> gitlab-org/gitlab",
        ],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
