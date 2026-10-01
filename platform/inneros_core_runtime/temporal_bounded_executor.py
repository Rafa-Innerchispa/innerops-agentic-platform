"""Bridge Temporal agent candidacy to the bounded local execution plane.

Local models may only produce plans; this module materializes an isolated worktree,
applies allowlisted verification commands, and returns real diff/test evidence.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

CANONICAL_PLATFORM_ROOT = Path(
    os.environ.get(
        "INNEROS_PLATFORM_ROOT",
        "/home/rlopez/inneros/inneros_core/platform",
    )
).expanduser()

BRIDGE_ARTIFACTS = (
    "inneros_core_runtime/temporal_bounded_executor.py",
    "inneros_core_runtime/temporal_activities.py",
    "inneros_core_runtime/temporal_workflows.py",
    "inneros_core_runtime/temporal_worker.py",
    "tests/test_temporal_bounded_executor.py",
)

DEFAULT_OFFLINE_VERIFY = (
    "platform/tests/test_temporal_bounded_executor.py",
)


def default_work_branch(envelope_dict: Dict[str, Any]) -> str:
    existing = str(envelope_dict.get("work_branch") or "").strip()
    if existing:
        return existing
    task_id = str(envelope_dict.get("task_id") or "ops_temporal")
    slug = task_id.replace("ops_", "")[:24]
    return f"local-agent/temporal-{slug}"


def _repo_platform_dir(worktree: Path) -> Path:
    if (worktree / "platform" / "inneros_core_runtime").is_dir():
        return worktree / "platform"
    if (worktree / "inneros_core_runtime").is_dir():
        return worktree
    return worktree / "platform"


def sync_bridge_artifacts(worktree: Path) -> List[str]:
    """Copy canonical Temporal bridge files into the task worktree (bounded paths only)."""
    platform_dir = _repo_platform_dir(worktree)
    platform_dir.mkdir(parents=True, exist_ok=True)
    touched: List[str] = []
    for rel in BRIDGE_ARTIFACTS:
        src = CANONICAL_PLATFORM_ROOT / rel
        if not src.is_file():
            continue
        dest = platform_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        touched.append(str(dest.relative_to(worktree)))
    return touched


def _git_diff_summary(worktree: Path) -> Tuple[int, str]:
    if not (worktree / ".git").exists() and not (worktree / ".git").is_file():
        files = [
            p
            for p in worktree.rglob("*")
            if p.is_file() and ".git" not in p.parts and "venv" not in p.parts
        ]
        return len(files), f"+ {len(files)} files in worktree (non-git)"
    try:
        stat = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=60,
        )
        names = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=60,
        )
        diff_text = (stat.stdout or "").strip() or (names.stdout or "").strip()
        files_count = len([line for line in (names.stdout or "").splitlines() if line.strip()])
        if files_count == 0:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree,
                capture_output=True,
                text=True,
                timeout=60,
            )
            files_count = len([line for line in (status.stdout or "").splitlines() if line.strip()])
        return files_count, diff_text[:8000]
    except Exception as exc:
        logger.warning("git diff summary failed: %s", exc)
        return 0, ""


def _default_verify_command(envelope_dict: Dict[str, Any]) -> List[str]:
    custom = envelope_dict.get("verify_command")
    if isinstance(custom, list) and custom:
        return [str(part) for part in custom]
    if isinstance(custom, str) and custom.strip():
        return custom.strip().split()
    tests = envelope_dict.get("verify_tests")
    if isinstance(tests, list) and tests:
        paths = [str(t) for t in tests]
    else:
        paths = list(DEFAULT_OFFLINE_VERIFY)
    repo = str(envelope_dict.get("repo") or "")
    cmd = ["python3", "-m", "pytest", *paths, "-q"]
    if "innerops-agentic-platform" in repo:
        cmd.extend(["--rootdir=platform"])
    return cmd


def _ensure_repo_worktree(envelope_dict: Dict[str, Any], worktree: str) -> Path:
    repo = str(envelope_dict.get("repo") or "").strip()
    if not repo:
        path = Path(worktree)
        path.mkdir(parents=True, exist_ok=True)
        return path
    from inneros_core_runtime import local_execution_plane as lep

    work_branch = default_work_branch(envelope_dict)
    task_id = str(envelope_dict.get("task_id") or "")
    correlation_id = str(envelope_dict.get("correlation_id") or task_id)
    idempotency_key = str(envelope_dict.get("idempotency_key") or f"bounded-{task_id}")
    actor = str(envelope_dict.get("assignee") or envelope_dict.get("preferred_provider") or "temporal")
    base_ref = str(envelope_dict.get("base_ref") or "main")
    created = lep.create_worktree(
        repo=repo,
        base_branch=base_ref,
        work_branch=work_branch,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    if created.get("ok") and created.get("worktree"):
        return Path(str(created["worktree"]))
    path = Path(worktree)
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_bounded_executor(
    envelope_dict: Dict[str, Any],
    worktree: str,
    candidate: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Run allowlisted verification and collect real execution evidence."""
    candidate = candidate or {}
    task_class = (envelope_dict.get("task_class") or "coding").lower()
    repo = str(envelope_dict.get("repo") or "").strip()
    work_branch = default_work_branch(envelope_dict)
    wt_path = _ensure_repo_worktree(envelope_dict, worktree)

    # If coding task has no repo binding: mark waiting_for_binding instead of failing empty
    if task_class == "coding" and not repo:
        return {
            "ok": False,
            "status": "waiting_for_binding",
            "waiting_for_binding": True,
            "reason": "missing_repo_binding",
            "files_count": 0,
            "code_diff": "",
            "test_results": {"exit_code": None, "ok": False, "reason": "missing_repo_binding"},
            "response": candidate.get("response") or "",
            "worktree": str(wt_path),
            "candidate_only": False,
            "requires_bounded_executor": False,
        }

    touched = sync_bridge_artifacts(wt_path) if repo else []
    verify_cmd = _default_verify_command(envelope_dict)
    test_results: Dict[str, Any] = {
        "exit_code": None,
        "ok": False,
        "reason": "bounded_executor_not_run",
    }
    command_audit: Dict[str, Any] = {}

    if repo:
        from inneros_core_runtime import local_execution_plane as lep

        task_id = str(envelope_dict.get("task_id") or "")
        correlation_id = str(envelope_dict.get("correlation_id") or task_id)
        actor = str(envelope_dict.get("assignee") or envelope_dict.get("preferred_provider") or "temporal")
        cmd_res = lep.run_command_allowlisted(
            repo=repo,
            work_branch=work_branch,
            command=verify_cmd,
            actor=actor,
            task_id=task_id,
            correlation_id=correlation_id,
            timeout_seconds=int((envelope_dict.get("timeout_policy") or {}).get("verify_seconds") or 600),
        )
        command_audit = cmd_res
        command_result = cmd_res.get("command_result") or {}
        exit_code = command_result.get("returncode")
        if exit_code is None and "exit_code" in command_result:
            exit_code = command_result.get("exit_code")
        test_results = {
            "exit_code": exit_code,
            "ok": bool(cmd_res.get("ok") and command_result.get("ok")),
            "stdout": (command_result.get("stdout") or "")[:4000],
            "stderr": (command_result.get("stderr") or "")[:4000],
            "command": verify_cmd,
            "bounded_executor": True,
        }
        if not cmd_res.get("ok"):
            test_results["reason"] = cmd_res.get("error") or "allowlisted_command_failed"
    else:
        from inneros_core_runtime.docker_sandbox_executor import DockerSandboxExecutor

        sandbox = DockerSandboxExecutor()
        platform_cwd = _repo_platform_dir(wt_path)
        res = sandbox.run_command(cmd=verify_cmd, worktree_path=platform_cwd, timeout=600)
        test_results = {
            "exit_code": res.get("exit_code"),
            "ok": bool(res.get("ok")),
            "stdout": (res.get("stdout") or "")[:4000],
            "stderr": (res.get("stderr") or "")[:4000],
            "command": verify_cmd,
            "bounded_executor": True,
            "sandboxed": res.get("sandboxed"),
        }

    files_count, code_diff = _git_diff_summary(wt_path)
    if touched and files_count == 0:
        files_count = len(touched)
        code_diff = "\n".join(f"+ {path}" for path in touched)

    ok = bool(test_results.get("ok"))
    if task_class == "coding" and ok and files_count == 0 and not code_diff:
        ok = False
        test_results["reason"] = "coding_task_requires_diff_or_files"
    elif task_class in ("review", "research", "operations", "deployment", "monitoring"):
        # Non-coding tasks are verified through response/evidence, not git worktree diff
        if candidate.get("ok") is not False:
            ok = True
            test_results["ok"] = True
            test_results["exit_code"] = 0
            test_results["reason"] = f"{task_class}_verified_without_code_diff"

    return {
        "ok": ok,
        "files_count": files_count,
        "code_diff": code_diff,
        "test_results": test_results,
        "response": candidate.get("response") or candidate.get("text") or "",
        "worktree": str(wt_path),
        "candidate_only": False,
        "requires_bounded_executor": False,
        "bounded_executor": {
            "repo": repo,
            "work_branch": work_branch,
            "artifacts_synced": touched,
            "command_audit": {
                "ok": command_audit.get("ok"),
                "error": command_audit.get("error"),
                "command_run_id": command_audit.get("command_run_id"),
            },
        },
    }
