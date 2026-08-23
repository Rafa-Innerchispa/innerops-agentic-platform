"""Bounded 1-to-N ops task scheduler for InnerOS dev swarm.

This module intentionally does not run arbitrary shell. It turns approved
``ralfia_ops_tasks`` into durable worker records and delegates repo preparation
to the safe ``local_execution_plane.dev_swarm_launch_task`` primitive.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import coordination_live, local_execution_plane, local_model_router, mongo_store

SCHEDULER_STATE_KEY = "dev_swarm_scheduler"
WORKERS_COL = "ralfia_dev_swarm_workers"
DEFAULT_MAX_CONCURRENT = 4
STALE_WORKER_SECONDS = 3600
ELIGIBLE_STATUSES = ("proposed",)
PRIORITY_ORDER = {"critical": 0, "p0": 1, "p1": 2, "normal": 3, "p2": 4, "low": 5}
SAFE_INNEROS_REPO = "Rafa-Innerchispa/innerops-agentic-platform"
ALLOWED_ASSIGNEES = {"codex", "chatgpt", "antigravity", "cursor", "ralfia", "gemini"}
TERMINAL_EXECUTOR_STATUSES = {"executed", "needs_implementation", "failed", "blocked"}
CURRENT_SAFE_TASK_IDS = {
    "ops_e7cacfc4a525",
    "ops_ca2281d54189",
    "ops_4afe0b330d8a",
    "ops_f61caab418a2",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _db():
    return mongo_store.get_db()


def _state() -> dict[str, Any]:
    doc = mongo_store.get_coordination_state(SCHEDULER_STATE_KEY)
    state = dict(doc.get("state") or {}) if doc.get("ok") else {}
    state.pop("_id", None)
    state.pop("key", None)
    state.setdefault("enabled", False)
    state.setdefault("max_concurrent", DEFAULT_MAX_CONCURRENT)
    state.setdefault("primary_node", "amd")
    state.setdefault("secondary_node", "intel")
    return state


def _save_state(patch: dict[str, Any]) -> dict[str, Any]:
    state = _state()
    state.update(patch)
    state["updated_at"] = _now()
    mongo_store.upsert_coordination_state(key=SCHEDULER_STATE_KEY, data=state)
    return state


def _priority_key(task: dict[str, Any]) -> tuple[int, str]:
    return (PRIORITY_ORDER.get(str(task.get("priority") or "normal").lower(), 9), str(task.get("created_at") or ""))


def _task_doc(task_id: str) -> dict[str, Any] | None:
    return _db()[coordination_live.OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0})


def _worker_worktree(worker: dict[str, Any]) -> str | None:
    launch = worker.get("launch") or {}
    worktree = launch.get("worktree") if isinstance(launch, dict) else None
    if isinstance(worktree, dict):
        return worktree.get("worktree")
    return None


def _worker_objective(worker: dict[str, Any], task: dict[str, Any] | None) -> str:
    if task:
        lines = [str(task.get("title") or ""), ""]
        lines.extend(str(item) for item in task.get("checklist") or [])
        return "\n".join(lines).strip()
    plan = ((worker.get("launch") or {}).get("plan") or {}) if isinstance(worker.get("launch"), dict) else {}
    return str(plan.get("objective") or worker.get("task_id") or "").strip()


def _infer_repo(task: dict[str, Any]) -> str | None:
    tags = set(str(x) for x in task.get("tags") or [])
    if "dev_swarm_fixture" in tags:
        return SAFE_INNEROS_REPO
    task_id = str(task.get("task_id") or "")
    if task_id in CURRENT_SAFE_TASK_IDS:
        return SAFE_INNEROS_REPO
    repo = str(task.get("repo") or task.get("repository") or "").strip()
    if repo.startswith("Rafa-Innerchispa/"):
        return repo
    text = " ".join(str(task.get(k) or "") for k in ("title", "correlation_id")).lower()
    text += " " + " ".join(str(x) for x in task.get("checklist") or []).lower()
    correlation = str(task.get("correlation_id") or "")
    if correlation != "inneros-build-rugir-20260823":
        return None
    current_markers = (
        "inneros",
        "innerops",
        "zkteco",
        "hikvision",
        "vigil",
        "integration guardian",
        "gcp",
        "gemini agent runtime",
        "scheduler 1",
        "autonomous",
        "dev swarm",
        "codex-continuity",
        "parallel-swarm",
    )
    excluded_markers = ("xprize", "devpost", "workforce.pcdoctor.ai", "femar")
    if any(marker in text for marker in current_markers) and not any(marker in text for marker in excluded_markers):
        return SAFE_INNEROS_REPO
    return None


def _active_worker_query() -> dict[str, Any]:
    return {
        "status": {"$in": ["starting", "running"]},
        "$or": [
            {"executor.status": {"$exists": False}},
            {"executor.status": {"$nin": list(TERMINAL_EXECUTOR_STATUSES)}},
        ],
    }


def reconcile_capacity_state(reason: str = "scheduler_tick") -> dict[str, Any]:
    db = _db()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    stale_before = now.timestamp() - STALE_WORKER_SECONDS
    terminal_filter = {
        "status": {"$in": ["starting", "running"]},
        "executor.status": {"$in": list(TERMINAL_EXECUTOR_STATUSES)},
    }
    terminal_res = db[WORKERS_COL].update_many(
        terminal_filter,
        {
            "$set": {
                "status": "verification",
                "capacity_reconciled_at": now_iso,
                "capacity_reconcile_reason": reason,
            }
        },
    )
    stale_workers = []
    for worker in db[WORKERS_COL].find(
        {
            "status": {"$in": ["starting", "running"]},
            "$or": [{"executor.status": {"$exists": False}}, {"executor.status": {"$nin": list(TERMINAL_EXECUTOR_STATUSES)}}],
        },
        {"_id": 0, "task_id": 1, "last_heartbeat_at": 1, "updated_at": 1},
    ):
        heartbeat = _parse_dt(worker.get("last_heartbeat_at") or worker.get("updated_at"))
        if heartbeat and heartbeat.timestamp() < stale_before:
            stale_workers.append(worker.get("task_id"))
    stale_res = None
    if stale_workers:
        stale_res = db[WORKERS_COL].update_many(
            {"task_id": {"$in": [task_id for task_id in stale_workers if task_id]}},
            {
                "$set": {
                    "status": "stale",
                    "capacity_reconciled_at": now_iso,
                    "capacity_reconcile_reason": reason,
                    "blocker": "stale_worker_heartbeat_expired",
                }
            },
        )
    lock_res = db["ralfia_coordination_locks"].update_many(
        {"status": "active", "expires_at": {"$lt": now_iso}},
        {"$set": {"status": "expired", "expired_at": now_iso, "updated_at": now_iso, "expired_by": "dev_swarm_reconciler"}},
    )
    active = db[WORKERS_COL].count_documents(_active_worker_query())
    return {
        "ok": True,
        "reason": reason,
        "terminal_workers_reconciled": terminal_res.modified_count,
        "stale_workers_reconciled": 0 if stale_res is None else stale_res.modified_count,
        "expired_locks": lock_res.modified_count,
        "active_worker_count": active,
    }


def _eligible_reason(task: dict[str, Any]) -> tuple[bool, str, str | None]:
    status = str(task.get("status") or "").lower()
    if status not in ELIGIBLE_STATUSES and not (status in {"accepted", "in_progress", "blocked"} and task.get("owner") == "dev_swarm"):
        return False, "status_not_proposed", None
    assignee = str(task.get("assignee") or "").lower()
    if assignee not in ALLOWED_ASSIGNEES:
        return False, f"assignee_not_swarm_eligible:{assignee}", None
    repo = _infer_repo(task)
    if not repo:
        return False, "repo_not_inferred", None
    policy = local_execution_plane.repo_policy_status(repo)
    if not policy.get("ok"):
        return False, f"repo_policy_denied:{policy.get('error')}", repo
    if policy.get("write_scope") in {"none", "read_only"}:
        return False, "repo_read_only_policy", repo
    return True, "eligible", repo


def scheduler_status() -> dict[str, Any]:
    db = _db()
    reconcile = reconcile_capacity_state(reason="scheduler_status")
    state = _state()
    active_statuses = ["accepted", "in_progress", "blocked", "awaiting_approval", "verification"]
    workers = list(db[WORKERS_COL].find({}, {"_id": 0}).sort("updated_at", -1).limit(20))
    return {
        "ok": True,
        "state": state,
        "reconcile": reconcile,
        "active_worker_count": db[WORKERS_COL].count_documents(_active_worker_query()),
        "proposed_count": db[coordination_live.OPS_TASKS_COL].count_documents({"status": "proposed"}),
        "active_ops_count": db[coordination_live.OPS_TASKS_COL].count_documents({"status": {"$in": active_statuses}}),
        "recent_workers": workers,
    }


def executor_status() -> dict[str, Any]:
    db = _db()
    reconcile = reconcile_capacity_state(reason="executor_status")
    running = list(db[WORKERS_COL].find(_active_worker_query(), {"_id": 0}).sort("updated_at", -1).limit(20))
    executed = db[WORKERS_COL].count_documents({"executor.status": {"$in": ["executed", "needs_implementation"]}})
    failed = db[WORKERS_COL].count_documents({"executor.status": "failed"})
    return {
        "ok": True,
        "reconcile": reconcile,
        "running_count": len(running),
        "executed_count": executed,
        "failed_count": failed,
        "recent_running": [
            {
                "task_id": w.get("task_id"),
                "branch": w.get("branch"),
                "repo": w.get("repo"),
                "worktree": _worker_worktree(w),
                "executor": w.get("executor"),
            }
            for w in running
        ],
    }


def _command_succeeded(item: dict[str, Any]) -> bool:
    result = item.get("result") or {}
    command_result = result.get("command_result")
    if isinstance(command_result, dict):
        return bool(result.get("ok")) and bool(command_result.get("ok"))
    return bool(result.get("ok"))


def _test_command_for_worktree(worktree: Path) -> list[str] | None:
    if (worktree / "package.json").exists():
        return ["npm", "run", "lint"]
    if (worktree / "pyproject.toml").exists() or (worktree / "requirements.txt").exists():
        return ["python3", "-m", "compileall", "."]
    return None


def scheduler_start(max_concurrent: int = DEFAULT_MAX_CONCURRENT, dry_run: bool = False) -> dict[str, Any]:
    max_c = max(1, min(int(max_concurrent or DEFAULT_MAX_CONCURRENT), 8))
    if dry_run:
        return {"ok": True, "dry_run": True, "would_set": {"enabled": True, "max_concurrent": max_c}}
    state = _save_state({"enabled": True, "max_concurrent": max_c, "started_at": _now(), "stopped_at": None})
    coordination_live.bump_revision(reason="dev_swarm_scheduler enabled", source="dev_swarm")
    return {"ok": True, "state": state}


def scheduler_stop(reason: str = "", dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "dry_run": True, "would_set": {"enabled": False, "reason": reason}}
    state = _save_state({"enabled": False, "stopped_at": _now(), "stop_reason": reason[:300]})
    coordination_live.bump_revision(reason="dev_swarm_scheduler stopped", source="dev_swarm")
    return {"ok": True, "state": state}


def scheduler_tick(limit: int = 6, dry_run: bool = False, include_fixtures: bool = False) -> dict[str, Any]:
    db = _db()
    reconcile = reconcile_capacity_state(reason="scheduler_tick")
    state = _state()
    max_concurrent = max(1, min(int(state.get("max_concurrent") or DEFAULT_MAX_CONCURRENT), 8))
    active = db[WORKERS_COL].count_documents(_active_worker_query())
    capacity = max(0, max_concurrent - active)
    if not state.get("enabled") and not dry_run:
        return {"ok": True, "enabled": False, "started": [], "skipped": [], "capacity": capacity, "reconcile": reconcile}
    query: dict[str, Any] = {"status": "proposed"}
    if not include_fixtures:
        query["tags"] = {"$ne": "dev_swarm_fixture"}
        query["task_id"] = {"$in": list(CURRENT_SAFE_TASK_IDS)}
    scan_limit = max(max(1, min(limit, 25)) * 5, 50)
    tasks = list(db[coordination_live.OPS_TASKS_COL].find(query, {"_id": 0}).limit(scan_limit))
    retry_ids = [
        row["task_id"]
        for row in db[WORKERS_COL]
        .find(
            {"status": "blocked", "task_id": {"$in": list(CURRENT_SAFE_TASK_IDS)}},
            {"_id": 0, "task_id": 1},
        )
        .limit(max(1, min(limit, 25)))
        if row.get("task_id")
    ]
    if retry_ids:
        seen = {task.get("task_id") for task in tasks}
        retry_tasks = db[coordination_live.OPS_TASKS_COL].find(
            {"task_id": {"$in": retry_ids}, "owner": "dev_swarm", "status": {"$in": ["accepted", "in_progress", "blocked"]}},
            {"_id": 0},
        )
        tasks.extend(task for task in retry_tasks if task.get("task_id") not in seen)
    tasks.sort(key=_priority_key)
    started: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for task in tasks:
        if len(started) >= capacity and not dry_run:
            skipped.append({"task_id": task.get("task_id"), "reason": "capacity_full"})
            continue
        ok, reason, repo = _eligible_reason(task)
        if not ok:
            skipped.append({"task_id": task.get("task_id"), "reason": reason, "repo": repo})
            continue
        task_id = str(task.get("task_id"))
        branch = f"local-agent/{task_id}-{secrets.token_hex(3)}"
        objective = f"{task.get('title')}\n\n" + "\n".join(str(x) for x in task.get("checklist") or [])
        if dry_run:
            started.append({"task_id": task_id, "repo": repo, "branch": branch, "dry_run": True})
            continue
        if str(task.get("status") or "").lower() == "proposed":
            acc = coordination_live.update_ops_task_state(task_id, "accepted", actor="dev_swarm")
            if not acc.get("ok") and not acc.get("idempotent"):
                skipped.append({"task_id": task_id, "reason": f"accept_failed:{acc.get('error')}", "details": acc})
                continue
            prog = coordination_live.update_ops_task_state(task_id, "in_progress", actor="dev_swarm")
            if not prog.get("ok") and not prog.get("idempotent"):
                skipped.append({"task_id": task_id, "reason": f"start_failed:{prog.get('error')}", "details": prog})
                continue
        launch = local_execution_plane.dev_swarm_launch_task(
            repo=repo or SAFE_INNEROS_REPO,
            objective=objective[:4000],
            work_branch=branch,
            base_branch="main",
            actor="dev_swarm",
            task_id=task_id,
            correlation_id=str(task.get("correlation_id") or f"dev-swarm-{task_id}"),
            idempotency_key=f"dev-swarm-scheduler-{task_id}",
            dry_run=False,
        )
        lock_release: dict[str, Any] | None = None
        if launch.get("ok"):
            lock_release = local_execution_plane.release_lock(
                repo=repo or SAFE_INNEROS_REPO,
                actor="dev_swarm",
                task_id=task_id,
                correlation_id=str(task.get("correlation_id") or f"dev-swarm-{task_id}"),
            )
            launch["post_launch_lock_release"] = lock_release
        worker = {
            "worker_id": f"worker_{secrets.token_hex(6)}",
            "task_id": task_id,
            "repo": repo,
            "branch": branch,
            "node": state.get("primary_node") or "amd",
            "status": "running" if launch.get("ok") else "blocked",
            "launch": launch,
            "created_at": _now(),
            "updated_at": _now(),
            "last_heartbeat_at": _now(),
        }
        worktree_path = ((launch.get("worktree") or {}).get("worktree") if isinstance(launch.get("worktree"), dict) else None)
        db[WORKERS_COL].update_one({"task_id": task_id}, {"$set": worker}, upsert=True)
        coordination_live.heartbeat_ops_task(
            task_id,
            "dev_swarm",
            next_action="Local worktree started; inspect worktree, run focused tests, report completion evidence.",
            blocker=None if launch.get("ok") else str(launch.get("error") or "launch_failed")[:300],
            files_touched=[str(worktree_path)] if worktree_path else [],
        )
        started.append({"task_id": task_id, "repo": repo, "branch": branch, "worker": worker["worker_id"], "launch_ok": launch.get("ok")})
    _save_state({"last_tick_at": _now(), "last_tick_started": len(started), "last_tick_skipped": len(skipped)})
    return {"ok": True, "enabled": bool(state.get("enabled")), "capacity": capacity, "active_worker_count": active, "reconcile": reconcile, "started": started, "skipped": skipped}


def _executor_report_markdown(
    *,
    worker: dict[str, Any],
    task: dict[str, Any] | None,
    commands: list[dict[str, Any]],
    local_model: dict[str, Any],
    outcome: str,
) -> str:
    title = (task or {}).get("title") or worker.get("task_id")
    objective = _worker_objective(worker, task)
    lines = [
        f"# Dev Swarm Executor Report — {worker.get('task_id')}",
        "",
        f"- Task: `{worker.get('task_id')}`",
        f"- Title: {title}",
        f"- Repo: `{worker.get('repo')}`",
        f"- Branch: `{worker.get('branch')}`",
        f"- Worktree: `{_worker_worktree(worker) or 'missing'}`",
        f"- Outcome: `{outcome}`",
        f"- Generated: `{_now()}`",
        "",
        "## Objective",
        "",
        objective[:4000] or "_No objective found._",
        "",
        "## Checks",
        "",
    ]
    for item in commands:
        cmd = " ".join(item.get("command") or [])
        result = item.get("result") or {}
        command_result = result.get("command_result") or result
        lines.extend(
            [
                f"### `{cmd}`",
                "",
                f"- ok: `{bool(result.get('ok'))}`",
                f"- returncode: `{command_result.get('returncode', 'n/a')}`",
                "",
                "```text",
                str(command_result.get("stdout") or command_result.get("stderr") or "")[:6000],
                "```",
                "",
            ]
        )
    lines.extend(["## Local Model Plan", ""])
    if local_model.get("ok"):
        response = local_model.get("response") or local_model.get("text") or local_model.get("content") or ""
        lines.extend([str(response)[:8000], ""])
    else:
        lines.extend([f"Local model unavailable or declined: `{local_model.get('error') or local_model.get('reason')}`", ""])
    lines.extend(
        [
            "## Executor Boundary",
            "",
            "This executor ran allowlisted diagnostics, generated a local plan, wrote evidence, and committed it on the isolated branch. Product code changes still require a specialized implementation agent unless the generated patch is explicitly approved and applied through Local Execution Plane.",
            "",
        ]
    )
    return "\n".join(lines)


def executor_tick(limit: int = 2, dry_run: bool = False, run_tests: bool = True) -> dict[str, Any]:
    db = _db()
    workers = list(
        db[WORKERS_COL]
        .find(
            {
                "status": "running",
                "$or": [
                    {"executor.status": {"$exists": False}},
                    {"executor.status": {"$in": ["pending", "failed_retryable"]}},
                ],
            },
            {"_id": 0},
        )
        .sort("created_at", 1)
        .limit(max(1, min(int(limit or 2), 6)))
    )
    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for worker in workers:
        task_id = str(worker.get("task_id") or "")
        repo = str(worker.get("repo") or "")
        branch = str(worker.get("branch") or "")
        correlation_id = str(((worker.get("launch") or {}).get("plan") or {}).get("correlation_id") or f"dev-swarm-{task_id}")
        if not task_id or not repo or not branch:
            skipped.append({"task_id": task_id, "reason": "worker_missing_metadata"})
            continue
        task = _task_doc(task_id)
        objective = _worker_objective(worker, task)
        if dry_run:
            executed.append({"task_id": task_id, "repo": repo, "branch": branch, "dry_run": True})
            continue
        commands: list[dict[str, Any]] = []
        for command in (["git", "status", "--short", "--branch"], ["git", "diff", "--check"], ["git", "diff", "--stat"]):
            result = local_execution_plane.run_command_allowlisted(
                repo=repo,
                work_branch=branch,
                command=list(command),
                actor="dev_swarm",
                task_id=task_id,
                correlation_id=correlation_id,
                timeout_seconds=120,
            )
            commands.append({"command": list(command), "result": result})
        if run_tests:
            test_command = _test_command_for_worktree(Path(_worker_worktree(worker)))
            if test_command:
                test_result = local_execution_plane.run_command_allowlisted(
                    repo=repo,
                    work_branch=branch,
                    command=test_command,
                    actor="dev_swarm",
                    task_id=task_id,
                    correlation_id=correlation_id,
                    timeout_seconds=300,
                    max_output_bytes=20000,
                )
                commands.append({"command": test_command, "result": test_result})
            else:
                commands.append({
                    "command": ["test-suite"],
                    "result": {"ok": True, "skipped": True, "reason": "no_package_or_python_project_markers"},
                })
        prompt = (
            "You are a local implementation planner inside InnerOS. Produce a concrete, bounded plan for this task. "
            "Do not claim code was changed. Identify safe files/modules to inspect or edit next, tests to run, and blockers.\n\n"
            f"Task:\n{objective[:6000]}\n\n"
            f"Branch: {branch}\nRepo: {repo}\n"
        )
        local_model = local_model_router.run_local_model(task_type="coding", prompt=prompt, max_tokens=900)
        failed_checks = [item for item in commands if not _command_succeeded(item)]
        outcome = "needs_implementation" if failed_checks or not local_model.get("ok") else "executed"
        report_path = f"docs/dev-swarm/{task_id}-executor.md"
        content = _executor_report_markdown(
            worker=worker,
            task=task,
            commands=commands,
            local_model=local_model,
            outcome=outcome,
        )
        write = local_execution_plane.write_file(
            repo=repo,
            work_branch=branch,
            path=report_path,
            content=content,
            actor="dev_swarm",
            task_id=task_id,
            correlation_id=correlation_id,
            idempotency_key=f"dev-swarm-executor-write-{task_id}",
        )
        commit = local_execution_plane.commit_branch(
            repo=repo,
            work_branch=branch,
            message=f"docs: add dev swarm executor report for {task_id}",
            actor="dev_swarm",
            task_id=task_id,
            correlation_id=correlation_id,
            idempotency_key=f"dev-swarm-executor-commit-{task_id}",
        )
        evidence = {
            "executor": "dev_swarm_executor",
            "outcome": outcome,
            "commands": commands,
            "local_model_ok": bool(local_model.get("ok")),
            "report_path": report_path,
            "write": write,
            "commit": commit,
        }
        report = local_execution_plane.report_evidence(repo, branch, "dev_swarm", task_id, correlation_id, outcome, evidence)
        db[WORKERS_COL].update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "executor": {
                        "status": outcome,
                        "updated_at": _now(),
                        "report_path": report_path,
                        "commands_ok": not failed_checks,
                        "local_model_ok": bool(local_model.get("ok")),
                        "commit": commit,
                        "evidence": report,
                    },
                    "updated_at": _now(),
                }
            },
        )
        coordination_live.heartbeat_ops_task(
            task_id,
            "dev_swarm",
            next_action=(
                "Executor produced report and branch commit; specialized implementation agent should apply bounded product changes."
                if outcome == "needs_implementation"
                else "Executor report committed; ready for verification or implementation follow-up."
            ),
            blocker="needs_product_implementation" if outcome == "needs_implementation" else None,
            files_touched=[report_path],
        )
        executed.append(
            {
                "task_id": task_id,
                "repo": repo,
                "branch": branch,
                "outcome": outcome,
                "report_path": report_path,
                "commit_head": commit.get("head"),
                "commands_ok": not failed_checks,
                "local_model_ok": bool(local_model.get("ok")),
            }
        )
    _save_state({"last_executor_tick_at": _now(), "last_executor_executed": len(executed), "last_executor_skipped": len(skipped)})
    return {"ok": True, "executed": executed, "skipped": skipped}


def create_fixture_tasks(count: int = 2) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    for idx in range(max(1, min(int(count or 2), 5))):
        task = coordination_live.create_ops_task(
            assignee="codex",
            title=f"Fixture dev swarm scheduler {idx + 1}",
            checklist=["Verify scheduler can accept and launch a safe isolated worktree.", "Do not modify production."],
            evidence_required=["worker record", "worktree evidence"],
            priority="p0",
            from_agent="DEV_SWARM",
            correlation_id=f"dev-swarm-fixture-{secrets.token_hex(4)}",
            related_project="innerops-agentic-platform",
        )
        if task.get("ok"):
            db = _db()
            db[coordination_live.OPS_TASKS_COL].update_one(
                {"task_id": task.get("task_id")},
                {"$addToSet": {"tags": "dev_swarm_fixture"}},
            )
        created.append(task)
    return {"ok": True, "created": created}
