"""Bounded ops execution for Codex/Antigravity — canary + optional Codex CLI (fail-closed)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from inneros_core_runtime import execution_receipts as receipts
from inneros_core_runtime import interactive_ops_runner as ior
from inneros_core_runtime import ops_model_execution_journal as omj
from inneros_core_runtime import temporal_bounded_executor as tbe
from inneros_core_runtime.coordination_live import OPS_TASKS_COL, heartbeat_ops_task
from raphiia_openai import mongo_store

PROVIDER_CANARY_MARKERS = {
    "codex": "docs/CODEX_CANARY.md",
    "antigravity": "docs/ANTIGRAVITY_CANARY.md",
}

CANARY_VERIFY_TEST = "platform/tests/test_provider_ops_canary_receipt.py"


def _codex_bin() -> str:
    for candidate in (
        Path.home() / ".local/bin/codex",
        Path.home() / ".local/node_modules/.bin/codex",
    ):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("codex") or "codex"


def _task_blob(task: dict[str, Any]) -> str:
    payload = task.get("payload") or {}
    return " ".join(
        str(x or "")
        for x in (
            task.get("title"),
            task.get("objective"),
            json.dumps(payload) if isinstance(payload, dict) else payload,
        )
    ).lower()


def is_innocuous_canary_task(task: dict[str, Any], provider: str) -> bool:
    prov = (provider or "").strip().lower()
    marker = PROVIDER_CANARY_MARKERS.get(prov, "")
    if not marker:
        return False
    blob = _task_blob(task)
    if marker.lower() in blob:
        return True
    if f"[{prov}_canary]" in blob or "[provider_canary]" in blob:
        return True
    payload = task.get("payload") or {}
    return isinstance(payload, dict) and payload.get("provider_canary") == prov


def _model_exec_allowed(provider: str) -> bool:
    if provider == "codex":
        return os.getenv("INNEROS_CODEX_OPS_ALLOW_MODEL_EXEC", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if provider == "antigravity":
        return os.getenv("INNEROS_ANTIGRAVITY_OPS_ALLOW_MODEL_EXEC", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    return False


def _git_commit_worktree(worktree: Path, message: str) -> dict[str, Any]:
    try:
        status = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if not (status.stdout or "").strip():
            return {"ok": True, "idempotent": True, "commit_sha": receipts.git_head(worktree)}
        subprocess.run(["git", "-C", str(worktree), "add", "-A"], timeout=60, check=False)
        commit = subprocess.run(
            ["git", "-C", str(worktree), "commit", "-m", message[:200]],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if commit.returncode != 0:
            return {"ok": False, "error": "git_commit_failed", "detail": (commit.stderr or "")[-500:]}
        return {"ok": True, "commit_sha": receipts.git_head(worktree)}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": type(exc).__name__}


def _run_bounded_canary(task: dict[str, Any], provider: str, worktree: Path) -> dict[str, Any]:
    prov = provider.strip().lower()
    marker = PROVIDER_CANARY_MARKERS[prov]
    tid = str(task.get("task_id") or "")
    envelope = {
        **task,
        "assignee": prov,
        "preferred_provider": prov,
        "task_class": "coding",
        "required_objective_paths": [marker],
        "verify_command": [
            "python3",
            "-m",
            "unittest",
            "tests.test_provider_ops_canary_receipt",
        ],
        "sync_bridge_artifacts": False,
        # Use the claim worktree in-place; do not spawn a second LEP worktree.
        "repo": "",
    }
    bounded = tbe.run_bounded_executor(envelope, str(worktree), candidate={"ok": True, "response": ""})
    commit_msg = f"ops {tid} {prov} canary"
    commit = _git_commit_worktree(worktree, commit_msg)
    if not commit.get("ok"):
        bounded["ok"] = False
        bounded["commit_error"] = commit.get("error")
    return {**bounded, "primary": "bounded_canary", "commit": commit}


def _parse_codex_usage(events: str) -> tuple[str | None, dict[str, int]]:
    thread_id = None
    usage: dict[str, int] = {}
    for line in (events or "").splitlines():
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if event.get("type") == "thread.started":
            thread_id = str(event.get("thread_id") or "") or None
        elif event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = {
                str(k): int(v)
                for k, v in event["usage"].items()
                if isinstance(v, (int, float))
            }
    return thread_id, usage


def _run_codex_cli(task: dict[str, Any], worktree: Path, *, pinned_model: str) -> dict[str, Any]:
    if not shutil.which(_codex_bin()) and not Path(_codex_bin()).is_file():
        return {"ok": False, "error": "blocked_provider_unavailable", "detail": "codex_cli_missing"}
    objective = str(task.get("objective") or task.get("title") or "").strip()
    if len(objective) > 8000:
        objective = objective[:8000]
    guarded = (
        "Trabaja solo en este repositorio. No despliegues ni toques credenciales. "
        f"Solicitud: {objective}"
    )
    with tempfile.NamedTemporaryFile(prefix="codex-ops-", suffix=".txt", delete=False) as out:
        output_path = Path(out.name)
    cmd = [
        _codex_bin(),
        "exec",
        "--ignore-user-config",
        "-m",
        pinned_model,
        "-c",
        "shell_environment_policy.inherit=none",
        "--sandbox",
        "workspace-write",
        "--ephemeral",
        "--json",
        "--cd",
        str(worktree),
        "-o",
        str(output_path),
        guarded,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=int(os.getenv("INNEROS_CODEX_OPS_EXEC_TIMEOUT", "900")),
            check=False,
        )
        thread_id, usage = _parse_codex_usage(proc.stdout or "")
        resolved = pinned_model
        m = re.search(r'"model"\s*:\s*"([^"]+)"', proc.stdout or "")
        if m:
            resolved = m.group(1)
        return {
            "ok": proc.returncode == 0,
            "primary": "codex_cli_exec",
            "exit_code": proc.returncode,
            "configured_model": pinned_model,
            "resolved_model": resolved,
            "codex_thread_id": thread_id,
            "usage": usage or None,
            "stdout_tail": (proc.stdout or "")[-4000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
            "output_path": str(output_path),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "codex_exec_timeout", "primary": "codex_cli_exec"}
    finally:
        output_path.unlink(missing_ok=True)


def execute_claimed_task(task_id: str, provider: str) -> dict[str, Any]:
    """Run real bounded work for a claimed task; never forge COMPLETED without receipts."""
    tid = (task_id or "").strip()
    prov = (provider or "").strip().lower()
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": tid}
    token = str(task.get("claim_token") or "").strip()
    if not token:
        return {"ok": False, "error": "claim_token_required", "task_id": tid}
    worktree_raw = str(task.get("worktree") or task.get("local_worktree") or "").strip()
    worktree = Path(worktree_raw).expanduser()
    if not worktree.is_dir() or not (worktree / ".git").exists():
        return {"ok": False, "error": "worktree_required", "task_id": tid, "worktree": worktree_raw}

    pinned = ior.pinned_model(prov)
    before_sha = str(task.get("git_baseline_sha") or receipts.git_head(worktree)).strip()
    heartbeat_ops_task(tid, actor=prov, phase="bounded_executor", last_progress=f"{prov} headless start")

    runner_result: dict[str, Any]
    journal_extra: dict[str, Any] = {"execution_phase": "headless_worker"}

    if is_innocuous_canary_task(task, prov):
        runner_result = _run_bounded_canary(task, prov, worktree)
        omj.record_model_execution(
            tid,
            provider=prov,
            configured_model=pinned,
            resolved_model=None,
            model_source="bounded_canary_no_model_spend",
            transport="temporal_bounded_executor",
            extra=journal_extra,
        )
    elif prov == "codex" and _model_exec_allowed("codex"):
        runner_result = _run_codex_cli(task, worktree, pinned_model=pinned)
        omj.record_model_execution(
            tid,
            provider=prov,
            configured_model=pinned,
            resolved_model=str(runner_result.get("resolved_model") or pinned),
            model_source="codex_cli_exec",
            usage=runner_result.get("usage") if isinstance(runner_result.get("usage"), dict) else None,
            transport="codex_cli_exec",
            extra={**journal_extra, "codex_thread_id": runner_result.get("codex_thread_id")},
        )
        if runner_result.get("ok"):
            commit = _git_commit_worktree(worktree, f"ops {tid} codex")
            runner_result["commit"] = commit
    else:
        blocked = {
            "ok": False,
            "error": "blocked_execution_not_wired",
            "task_id": tid,
            "provider": prov,
            "hint": (
                "Use innocuous canary objective with provider marker path, or enable "
                "INNEROS_CODEX_OPS_ALLOW_MODEL_EXEC with owner-approved spend."
            ),
            "bounded_executor_plan": {
                "status": "BLOCKED_PENDING_BOUNDED_EXECUTOR",
                "required_steps": [
                    "claim_with_worktree_and_git_baseline_sha",
                    "bounded_canary_or_codex_cli_with_tools",
                    "committed_objective_receipt",
                    "complete_ops_task with test_results.exit_code",
                ],
            },
        }
        omj.record_model_execution(
            tid,
            provider=prov,
            configured_model=pinned,
            resolved_model=None,
            model_source="blocked",
            transport=None,
            extra={**journal_extra, "blocked_reason": blocked["error"]},
        )
        complete = ior.complete_ops_task(
            prov,
            tid,
            claim_token=token,
            status="blocked",
            evidence={
                "notes": f"{prov}_ops_headless_execute_one_fail_closed",
                "blocked_reason": blocked["error"],
                "headless_primary": f"{prov}_bounded_executor",
            },
        )
        return {**blocked, "complete": complete}

    test_results = runner_result.get("test_results") if isinstance(runner_result.get("test_results"), dict) else {}
    exit_code = test_results.get("exit_code")
    if exit_code is None and runner_result.get("exit_code") is not None:
        exit_code = runner_result.get("exit_code")
        test_results = {"exit_code": exit_code, "ok": exit_code == 0}

    if not runner_result.get("ok"):
        fail_evidence = {
            "notes": str(runner_result.get("error") or test_results.get("reason") or "bounded_run_failed")[:500],
            "headless_primary": runner_result.get("primary"),
            "git_before_sha": before_sha,
            "test_results": test_results if test_results.get("exit_code") is not None else {},
        }
        complete = ior.complete_ops_task(prov, tid, claim_token=token, status="blocked", evidence=fail_evidence)
        return {"ok": False, "task_id": tid, "runner": runner_result, "complete": complete}

    built = receipts.completion_evidence_from_worktree(
        worktree,
        before_sha,
        test_exit_code=int(exit_code) if exit_code is not None else None,
    )
    if not built.get("ok"):
        complete = ior.complete_ops_task(
            prov,
            tid,
            claim_token=token,
            status="blocked",
            evidence={
                "git_before_sha": before_sha,
                "test_results": test_results,
                "receipt_error": built.get("error"),
                "headless_primary": runner_result.get("primary"),
            },
        )
        return {"ok": False, "task_id": tid, "receipt": built, "complete": complete}

    evidence = {
        **built["evidence"],
        "headless_primary": runner_result.get("primary"),
        "execution_host": __import__("socket").gethostname(),
        "configured_model": pinned,
        "resolved_model": runner_result.get("resolved_model") or pinned,
    }
    if runner_result.get("usage"):
        evidence["model_usage"] = runner_result["usage"]
    complete = ior.complete_ops_task(
        prov,
        tid,
        claim_token=token,
        status="completed",
        evidence=evidence,
        commit_sha=str(built.get("commit_sha") or ""),
    )
    return {
        "ok": bool(complete.get("ok")),
        "task_id": tid,
        "runner": runner_result,
        "receipt": built,
        "complete": complete,
    }
