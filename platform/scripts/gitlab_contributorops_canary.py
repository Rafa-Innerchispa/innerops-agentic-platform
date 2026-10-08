#!/usr/bin/env python3
"""Live ContributorOps canary: auth, registry, fork remotes, RACB worktree probe, watcher health.

Usage:
  INNEROS_CORE_ROOT=/home/rlopez/inneros/inneros_core \\
  PYTHONPATH=/home/rlopez/inneros/inneros_core/platform \\
  python3 scripts/gitlab_contributorops_canary.py

Optional:
  GITLAB_CONTRIBUTOROPS_CANARY_ISSUE=631702   # issue duplicate guard (informational)
  GITLAB_CONTRIBUTOROPS_LIVE_PUSH=1           # push canary branch to origin then delete remote branch
  GITLAB_CONTRIBUTOROPS_SKIP_WATCH=1          # skip contributorops watch-once subprocess gate
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import gitlab_contributor_policy as gcp  # noqa: E402
from inneros_core_runtime import local_execution_plane as lep  # noqa: E402
from raphiia_openai import project_runtime_registry as prr  # noqa: E402

REPO = gcp.UPSTREAM_PROJECT
CANARY_STATE_DIR = Path(
    os.getenv(
        "GITLAB_CONTRIBUTOROPS_CANARY_STATE",
        "/home/rlopez/inneros/inneros_core/var/gitlab_contributorops",
    )
).expanduser()
CANARY_REPORT = CANARY_STATE_DIR / "canary-last.json"
AGENT_ROOT = Path("/home/rlopez/inneros/inneros_core/workspaces/gitlab-contributorops-agent")
PROBE_REL = "doc/innerchispa/CONTRIBUTOROPS_CANARY.md"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gate(name: str, fn) -> dict[str, Any]:
    try:
        payload = fn()
        ok = bool(payload.get("ok")) if isinstance(payload, dict) else bool(payload)
        return {"name": name, "ok": ok, "detail": payload}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": {"error": str(exc)}}


def gate_auth_and_fork() -> dict[str, Any]:
    fork = gcp.resolve_authenticated_write_fork()
    from inneros_core_runtime import local_gitlab_plane as gl

    status = gl.gitlab_status()
    return {
        "ok": bool(status.get("auth_ok") and fork.get("ok")),
        "gitlab_auth_ok": status.get("auth_ok"),
        "user": (status.get("verified_user") or {}).get("username"),
        "write_fork": fork.get("write_fork_project"),
        "fork_ok": fork.get("ok"),
    }


def gate_issue_guard() -> dict[str, Any]:
    raw = os.getenv("GITLAB_CONTRIBUTOROPS_CANARY_ISSUE", "631702").strip()
    if not raw:
        return {"ok": True, "skipped": True}
    iid = int(raw)
    guard = gcp.issue_work_duplicate_check(REPO, iid, author_username="rafagye")
    return {
        "ok": bool(guard.get("ok")),
        "issue_iid": iid,
        "duplicate_open_work": guard.get("duplicate_open_work"),
        "safe_to_start_new_branch": guard.get("safe_to_start_new_branch"),
        "heuristic_hits": len(guard.get("heuristic_open_mrs_by_author") or []),
    }


def gate_registry_and_policy() -> dict[str, Any]:
    resolved = prr.resolve_project(project_id="gitlab-org-gitlab", repo=REPO)
    conf = lep._repo_config(REPO)
    paths_ok = conf.get("profile") == "ruby-tests-local-only" and "spec" in (conf.get("allowed_paths") or [])
    return {
        "ok": bool(resolved.get("ok") and paths_ok and conf.get("contributor_ops")),
        "registry_ok": resolved.get("ok"),
        "project_path": resolved.get("project_path"),
        "profile": conf.get("profile"),
        "source_path": conf.get("source_path"),
        "registry_backed": conf.get("registry_backed"),
    }


def gate_repo_hydrated() -> dict[str, Any]:
    inspect = lep.inspect_repo(REPO)
    remotes = lep.inspect_remotes(REPO, "", "cursor", "ops-contributorops-canary", "gitlab-contributorops-canary")
    validation = remotes.get("validation") or {}
    origin_ok = (validation.get("origin") or {}).get("ok")
    upstream_ok = (validation.get("upstream") or {}).get("ok")
    return {
        "ok": bool(inspect.get("ok") and inspect.get("source_exists") and remotes.get("ok") and origin_ok and upstream_ok),
        "source_exists": inspect.get("source_exists"),
        "head": (inspect.get("git_head") or {}).get("stdout", "").strip(),
        "origin_ok": origin_ok,
        "upstream_ok": upstream_ok,
    }


def gate_worktree_lane() -> dict[str, Any]:
    correlation_id = os.getenv("GITLAB_CONTRIBUTOROPS_CANARY_CORRELATION", "gitlab-contributorops-canary").strip()
    task_id = "ops-contributorops-canary"
    actor = "cursor"
    digest = hashlib.sha256(f"{correlation_id}|{_now()}".encode()).hexdigest()[:8]
    work_branch = f"chatgpt/canary-contributorops-{digest}"
    idempotency_key = f"canary-worktree-{digest}"
    conf = lep._repo_config(REPO)
    source = Path(str(conf.get("source_path") or "")).expanduser().resolve()
    worktree = Path(lep._worktree_path(REPO, work_branch, conf))
    cleanup_notes: list[str] = []

    lock = lep.acquire_lock(REPO, actor, task_id, correlation_id, ttl_seconds=900)
    if not lock.get("ok"):
        return {"ok": False, "stage": "acquire_lock", "lock": lock, "work_branch": work_branch}

    try:
        wt = lep.create_worktree(REPO, "master", work_branch, actor, task_id, correlation_id, idempotency_key)
        if not wt.get("ok"):
            return {"ok": False, "stage": "create_worktree", "worktree": wt, "work_branch": work_branch}

        deny_upstream = lep.push_branch(
            REPO,
            work_branch,
            actor,
            task_id,
            correlation_id,
            idempotency_key,
            remote="upstream",
            dry_run=True,
        )
        origin_dry = lep.push_branch(
            REPO,
            work_branch,
            actor,
            task_id,
            correlation_id,
            idempotency_key,
            remote="origin",
            dry_run=True,
        )

        probe_body = (
            f"# ContributorOps canary probe\n\nGenerated: {_now()}\nCorrelation: {correlation_id}\n"
            "This file is safe to delete; it validates bounded write + allowlisted git reads.\n"
        )
        written = lep.write_file(
            REPO,
            work_branch,
            PROBE_REL,
            probe_body,
            actor,
            task_id,
            correlation_id,
            idempotency_key,
        )
        status_cmd = lep.run_command_allowlisted(
            REPO,
            work_branch,
            ["git", "status", "--short", "--branch"],
            actor,
            task_id,
            correlation_id,
            timeout_seconds=60,
        )
        live_push: dict[str, Any] | None = None
        if os.getenv("GITLAB_CONTRIBUTOROPS_LIVE_PUSH", "").strip().lower() in {"1", "true", "yes"}:
            committed = lep.commit_branch(
                REPO,
                work_branch,
                "chore: contributorops canary probe [skip ci]",
                actor,
                task_id,
                correlation_id,
                idempotency_key,
            )
            pushed = lep.push_branch(
                REPO,
                work_branch,
                actor,
                task_id,
                correlation_id,
                idempotency_key,
                remote="origin",
                dry_run=False,
            )
            live_push = {"commit": committed, "push": pushed}
            if pushed.get("ok"):
                from inneros_core_runtime import local_gitlab_plane as gl

                fork = gcp.resolve_authenticated_write_fork()
                project = str(fork.get("write_fork_project") or "")
                encoded = gl.project_api_path(project)
                delete = gl._request(
                    "DELETE",
                    f"/projects/{encoded}/repository/branches/{work_branch.replace('/', '%2F')}",
                )
                live_push["remote_branch_delete"] = {"ok": delete.get("ok"), "detail": delete.get("error")}

        ok = bool(
            written.get("ok")
            and status_cmd.get("ok")
            and deny_upstream.get("error") == "upstream_push_forbidden"
            and origin_dry.get("ok")
            and origin_dry.get("dry_run") is True
        )
        if live_push is not None:
            ok = ok and bool((live_push.get("push") or {}).get("ok"))

        return {
            "ok": ok,
            "work_branch": work_branch,
            "worktree": str(worktree),
            "written": written.get("ok"),
            "status_cmd": status_cmd.get("ok"),
            "upstream_push_denied": deny_upstream.get("error"),
            "origin_push_dry_run": origin_dry.get("ok"),
            "live_push": live_push,
            "cleanup": cleanup_notes,
        }
    finally:
        lep.release_lock(REPO, actor, task_id, correlation_id)
        if worktree.exists():
            rm = subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=str(source),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            cleanup_notes.append(f"worktree_remove:{rm.returncode}")
        branch_del = subprocess.run(
            ["git", "branch", "-D", work_branch],
            cwd=str(source),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        cleanup_notes.append(f"branch_delete:{branch_del.returncode}")
        if (source / PROBE_REL).exists():
            try:
                (source / PROBE_REL).unlink()
                cleanup_notes.append("source_probe_unlink:0")
            except OSError as exc:
                cleanup_notes.append(f"source_probe_unlink:{exc}")


def gate_contributorops_watch() -> dict[str, Any]:
    if os.getenv("GITLAB_CONTRIBUTOROPS_SKIP_WATCH", "").strip().lower() in {"1", "true", "yes"}:
        return {"ok": True, "skipped": True}
    env = {
        **os.environ,
        "CONTRIBUTOROPS_INNEROS_BRIDGE": "1",
        "PYTHONPATH": f"{AGENT_ROOT / 'src'}:{PLATFORM_ROOT}",
    }
    health = subprocess.run(
        [sys.executable, "-m", "contributorops.cli", "health"],
        cwd=str(AGENT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        health_json = json.loads(health.stdout or "{}")
    except json.JSONDecodeError:
        health_json = {"parse_error": True, "stdout_tail": (health.stdout or "")[-500:]}
    watch = subprocess.run(
        [
            sys.executable,
            "-m",
            "contributorops.cli",
            "watch-once",
            "--manifest",
            str(AGENT_ROOT / "contributions.json"),
        ],
        cwd=str(AGENT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    watch_ok = watch.returncode == 0
    watch_errors = 0
    if watch.stdout.strip():
        try:
            payload = json.loads(watch.stdout)
            for row in payload.get("results") or []:
                if (row.get("event") or {}).get("event_type") == "provider_transient_error":
                    watch_errors += 1
        except json.JSONDecodeError:
            watch_ok = False
    return {
        "ok": bool(health_json.get("authenticated") and watch_ok and watch_errors == 0),
        "health_authenticated": health_json.get("authenticated"),
        "watch_returncode": watch.returncode,
        "provider_transient_errors": watch_errors,
    }


def gate_dev_swarm_scope() -> dict[str, Any]:
    scope = lep.dev_swarm_scope_status(repo=REPO)
    return {"ok": bool(scope.get("ok")), "policy": scope.get("policy")}


def main() -> int:
    CANARY_STATE_DIR.mkdir(parents=True, exist_ok=True)
    gates = [
        _gate("auth_and_fork", gate_auth_and_fork),
        _gate("registry_and_policy", gate_registry_and_policy),
        _gate("repo_hydrated_remotes", gate_repo_hydrated),
        _gate("issue_guard", gate_issue_guard),
        _gate("dev_swarm_scope", gate_dev_swarm_scope),
        _gate("worktree_lane", gate_worktree_lane),
        _gate("contributorops_watch", gate_contributorops_watch),
    ]
    ok = all(g["ok"] for g in gates)
    report = {
        "ok": ok,
        "checked_at": _now(),
        "repo": REPO,
        "correlation_hint": "gitlab-contributorops-canary",
        "gates": gates,
    }
    CANARY_REPORT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
