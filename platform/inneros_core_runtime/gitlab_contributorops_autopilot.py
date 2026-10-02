"""GitLab ContributorOps autopilot — repair MRs and bootstrap quick-win issues via Dev Swarm + push."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = "gitlab-org/gitlab"
CORRELATION = "gitlab-contributorops-autopilot"
PLATFORM_ROOT = Path(__file__).resolve().parents[1]
WORKER_SCRIPT = PLATFORM_ROOT / "scripts" / "gitlab_contributorops_autopilot_worker.py"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def autopilot_enabled() -> bool:
    if os.environ.get("GITLAB_CONTRIBUTOROPS_AUTOPILOT", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return os.environ.get("CONTRIBUTOROPS_INNEROS_BRIDGE", "").strip().lower() in {"1", "true", "yes", "on"}


def _repair_task_id(project: str, mr_iid: int, signature: str) -> str:
    digest = hashlib.sha256(f"{project}|{mr_iid}|{signature}".encode()).hexdigest()[:10]
    return f"ops-gitlab-repair-{mr_iid}-{digest}"


def _build_repair_objective(event: dict[str, Any], *, source_branch: str) -> str:
    event_type = str(event.get("event_type") or "repair")
    title = str(event.get("title") or "")
    issue = str(event.get("issue") or event.get("short_summary") or "")
    root = str(event.get("root_cause") or "")
    lines = [
        f"GitLab ContributorOps automatic repair for MR !{event.get('mr_iid')} ({event_type}).",
        f"Title: {title}",
        f"Branch: {source_branch} (keep this branch name; push to origin when done).",
        "Repo logical name: gitlab-org/gitlab (Ruby on Rails, EE paths allowed).",
    ]
    if issue:
        lines.append(f"Reviewer / pipeline context: {issue}")
    if root:
        lines.append(f"Failure hint: {root}")
    lines.extend(
        [
            "Fix the minimal product change and specs only under allowed Rails paths.",
            "Run allowlisted ruby-tests-local-only commands if feasible (targeted rspec).",
            "Do not widen scope beyond the MR intent.",
        ]
    )
    return "\n".join(lines)


def repair_merge_request_event(event: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    from inneros_core_runtime import dev_swarm_scheduler, gitlab_contributor_policy as gcp, local_execution_plane, local_gitlab_plane as gl

    project = str(event.get("project") or gcp.UPSTREAM_PROJECT).strip()
    mr_iid = int(event.get("mr_iid") or 0)
    if not mr_iid:
        return {"ok": False, "error": "mr_iid_required"}

    mr_res = gl.get_merge_request(project, mr_iid)
    if not mr_res.get("ok"):
        return {"ok": False, "error": "merge_request_unavailable", "detail": mr_res}
    mr = mr_res.get("merge_request") or {}
    if str(mr.get("state") or "").lower() in {"merged", "closed"}:
        return {"ok": True, "skipped": True, "reason": "mr_terminal", "state": mr.get("state")}

    source_branch = str(mr.get("source_branch") or "").strip()
    if not re.match(r"^(codex|chatgpt|cursor|antigravity|gemini|local-agent)/", source_branch):
        return {"ok": False, "error": "source_branch_not_allowlisted", "source_branch": source_branch}

    signature = str(event.get("failure_signature") or event.get("note_id") or event.get("event_type") or "repair")
    task_id = _repair_task_id(project, mr_iid, signature)
    objective = _build_repair_objective(event, source_branch=source_branch)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "task_id": task_id,
            "repo": REPO,
            "source_branch": source_branch,
            "objective_preview": objective[:1200],
        }

    exec_result = dev_swarm_scheduler.execute_ad_hoc_objective(
        repo=REPO,
        task_id=task_id,
        objective=objective,
        correlation_id=f"{CORRELATION}-mr-{mr_iid}",
        preferred_branch=source_branch,
        base_ref=source_branch,
        entrypoint="gitlab_contributorops_autopilot.repair",
        dry_run=False,
    )
    push_result: dict[str, Any] | None = None
    branch = str(exec_result.get("branch") or source_branch)
    if exec_result.get("ok"):
        push_result = local_execution_plane.push_branch(
            REPO,
            branch,
            "dev_swarm",
            task_id,
            f"{CORRELATION}-mr-{mr_iid}",
            f"push-{task_id}",
            remote="origin",
            dry_run=False,
        )
        exec_result["push"] = push_result
        exec_result["ok"] = bool(exec_result.get("ok") and push_result.get("ok"))

    return {
        "ok": bool(exec_result.get("ok")),
        "task_id": task_id,
        "mr_iid": mr_iid,
        "project": project,
        "source_branch": source_branch,
        "executor": exec_result,
        "at": _now(),
    }


def bootstrap_quick_win_issue(issue_iid: int, *, dry_run: bool = False) -> dict[str, Any]:
    from inneros_core_runtime import dev_swarm_scheduler, gitlab_contributor_policy as gcp, local_execution_plane

    guard = gcp.issue_work_duplicate_check(gcp.UPSTREAM_PROJECT, int(issue_iid), author_username="rafagye")
    if not guard.get("ok"):
        return {"ok": False, "error": "issue_guard_failed", "guard": guard}
    if guard.get("duplicate_open_work"):
        return {"ok": True, "skipped": True, "reason": "duplicate_open_work", "guard": guard}

    issue = guard.get("issue") or {}
    title = str(issue.get("title") or f"issue-{issue_iid}")
    description = re.sub(r"<[^>]+>", " ", str(issue.get("description") or ""))
    description = re.sub(r"\s+", " ", description).strip()[:6000]
    branch = f"chatgpt/{issue_iid}-{'-'.join(re.sub(r'[^a-z0-9]+', '-', title.lower())[:40].strip('-').split('-')[:5])}"
    task_id = f"ops-gitlab-issue-{issue_iid}"
    objective = (
        f"Implement GitLab upstream issue #{issue_iid}: {title}\n\n"
        f"{description}\n\n"
        "Follow GitLab contribution guidelines; minimal fix + specs; push to origin on branch "
        f"{branch}."
    )

    if dry_run:
        return {"ok": True, "dry_run": True, "task_id": task_id, "branch": branch, "issue_iid": issue_iid}

    launch = local_execution_plane.dev_swarm_launch_task(
        repo=REPO,
        objective=objective[:7000],
        base_branch="master",
        work_branch=branch,
        actor="chatgpt",
        task_id=task_id,
        correlation_id=f"{CORRELATION}-issue-{issue_iid}",
        idempotency_key=f"bootstrap-issue-{issue_iid}",
        dry_run=False,
    )
    if not launch.get("ok"):
        return {"ok": False, "stage": "dev_swarm_launch", "launch": launch}

    exec_result = dev_swarm_scheduler.execute_ad_hoc_objective(
        repo=REPO,
        task_id=f"{task_id}-impl",
        objective=objective[:7000],
        correlation_id=f"{CORRELATION}-issue-{issue_iid}",
        preferred_branch=branch,
        base_ref=branch,
        entrypoint="gitlab_contributorops_autopilot.bootstrap",
        dry_run=False,
    )
    push_result = None
    if exec_result.get("ok"):
        push_result = local_execution_plane.push_branch(
            REPO,
            branch,
            "dev_swarm",
            f"{task_id}-impl",
            f"{CORRELATION}-issue-{issue_iid}",
            f"push-{task_id}-impl",
            remote="origin",
            dry_run=False,
        )
        exec_result["push"] = push_result

    from inneros_core_runtime import local_gitlab_plane as gl

    mr = None
    if push_result and push_result.get("ok"):
        mr = gl.create_draft_merge_request(
            "gitlab-community/gitlab-org/gitlab",
            branch,
            gcp.UPSTREAM_PROJECT,
            target_branch="master",
            title=title[:180],
            description=f"Automated contribution for #{issue_iid}\n\n{objective[:4000]}",
            dry_run=False,
        )

    return {
        "ok": bool(launch.get("ok") and exec_result.get("ok") and (push_result or {}).get("ok")),
        "issue_iid": issue_iid,
        "branch": branch,
        "launch": launch,
        "executor": exec_result,
        "merge_request": mr,
        "at": _now(),
    }


def spawn_background_repair(event: dict[str, Any]) -> dict[str, Any]:
    if not WORKER_SCRIPT.exists():
        return {"ok": False, "error": "worker_script_missing", "path": str(WORKER_SCRIPT)}
    env = dict(os.environ)
    env.setdefault("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core")
    env.setdefault("PYTHONPATH", str(PLATFORM_ROOT))
    env["GITLAB_CONTRIBUTOROPS_AUTOPILOT"] = "1"
    log_dir = Path(env["INNEROS_CORE_ROOT"]) / "var" / "gitlab_contributorops"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "autopilot-repair.log"
    payload = json.dumps({"mode": "repair", "event": event}, ensure_ascii=False)
    python = PLATFORM_ROOT / "venv" / "bin" / "python3"
    if not python.exists():
        python = Path(sys.executable)
    with log_path.open("a", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(
            [str(python), str(WORKER_SCRIPT), "--payload", payload],
            env=env,
            cwd=str(PLATFORM_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {"ok": True, "spawned": True, "pid": proc.pid, "log_path": str(log_path)}


def handle_watch_result(result: dict[str, Any], *, ledger: Any | None = None) -> dict[str, Any]:
    """Consume one watch cycle row; spawn repair worker when policy requests it."""
    if not autopilot_enabled():
        return {"ok": True, "skipped": True, "reason": "autopilot_disabled"}
    decision = result.get("decision") or {}
    event = result.get("event") or {}
    if decision.get("pause_automation") or decision.get("terminal"):
        return {"ok": True, "skipped": True, "reason": "paused_or_terminal"}
    if decision.get("auto_action") != "repair":
        return {"ok": True, "skipped": True, "reason": "no_auto_action"}

    signature = str(event.get("failure_signature") or event.get("note_id") or event.get("event_type") or "repair")
    mr_iid = int(event.get("mr_iid") or 0)
    scope = f"gitlab:mr:{event.get('project')}:{mr_iid}:{signature}"
    reservation = None
    if ledger is not None:
        reservation = ledger.reserve(action_type="autopilot_repair", scope=scope, payload=event)
        if not reservation.allowed:
            return {"ok": True, "skipped": True, "reason": reservation.reason, "action_key": reservation.action_key}

    spawned = spawn_background_repair(event)
    if ledger is not None and spawned.get("ok") and reservation and reservation.allowed:
        ledger.mark_applied(reservation.action_key, external_id=str(spawned.get("pid")))
    return spawned
