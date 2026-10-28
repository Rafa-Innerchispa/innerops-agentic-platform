"""Shared, fail-closed proof of committed objective changes for InnerOS executors.

All coding executors (local Dev Swarm, Cursor, Codex, Antigravity) can use
these routines from the execution host. A Git SHA by itself is NOT proof
that an objective file was created during this task.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

_SHA = re.compile(r"^[a-fA-F0-9]{40}$")
_DENIED_PARTS = {".git", ".env", ".ssh", "__pycache__", "venv", ".venv"}


def git_head(worktree: Path) -> str:
    """Read actual worktree HEAD; return empty string on a non-repository."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        value = proc.stdout.strip()
        return value if proc.returncode == 0 and _SHA.fullmatch(value) else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def committed_objective_receipt(worktree: Path, before_sha: str) -> dict[str, Any]:
    """Attest existing files changed in commits *after* the task began.

    Only committed additions/changes/renames count. Never count untracked
    files, directories, caches, traversal paths or links outside worktree.
    """
    current = git_head(worktree)
    base = str(before_sha or "").strip()
    failure = {
        "ok": False, "commit_sha": current, "git_before_sha": base,
        "objective_paths": [], "objective_files_count": 0,
    }
    if not current or not _SHA.fullmatch(base):
        return {**failure, "error": "git_baseline_or_head_missing"}
    if current == base:
        return {**failure, "error": "no_new_commit_for_task"}
    try:
        root = worktree.resolve(strict=True)
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", "-z", "--name-only",
             "--diff-filter=ACMR", base, current, "--"],
            capture_output=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {**failure, "error": "objective_diff_unavailable"}
    if proc.returncode != 0:
        return {**failure, "error": "objective_diff_failed", "git_diff_rc": proc.returncode}

    objective_paths: list[str] = []
    for raw in proc.stdout.split(b"\x00"):
        if not raw:
            continue
        try:
            name = raw.decode("utf-8", errors="strict")
            rel = Path(name)
            if rel.is_absolute() or ".." in rel.parts or _DENIED_PARTS.intersection(rel.parts):
                continue
            full = (root / rel).resolve(strict=True)
            full.relative_to(root)
            if full.is_file() and name not in objective_paths:
                objective_paths.append(name)
        except (OSError, ValueError, UnicodeError):
            continue

    if not objective_paths:
        return {**failure, "error": "no_committed_objective_files"}
    return {
        "ok": True, "commit_sha": current, "git_before_sha": base,
        "objective_paths": sorted(objective_paths),
        "objective_files_count": len(objective_paths),
        "git_diff_rc": 0,
        "evidence_source": "git_committed_diff_on_execution_host",
    }


def runner_test_results_payload(runner_result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return runner-reported test_results for Mongo/Temporal receipts; never invent pass/fail."""
    if not isinstance(runner_result, dict):
        return None
    nested = runner_result.get("test_results")
    if isinstance(nested, dict) and nested.get("exit_code") is not None:
        try:
            exit_code = int(nested["exit_code"])
        except (TypeError, ValueError):
            return None
        ok = nested.get("ok")
        if ok is None:
            ok = exit_code == 0
        return {"exit_code": exit_code, "ok": bool(ok), **{k: v for k, v in nested.items() if k not in {"exit_code", "ok"}}}
    raw_exit = runner_result.get("exit_code")
    if raw_exit is not None:
        try:
            exit_code = int(raw_exit)
        except (TypeError, ValueError):
            return None
        return {"exit_code": exit_code, "ok": exit_code == 0}
    return None


def attach_runner_test_results(evidence: dict[str, Any], runner_result: dict[str, Any] | None) -> dict[str, Any]:
    """Merge authenticated runner pytest output into completion evidence when present."""
    payload = runner_test_results_payload(runner_result)
    if not payload:
        return evidence
    return {**evidence, "test_results": payload}


def completion_evidence_from_worktree(
    worktree: Path,
    before_sha: str,
    *,
    test_exit_code: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a Temporal/Mongo completion payload shared by Cursor, Codex, and Dev Swarm."""
    proof = committed_objective_receipt(worktree, before_sha)
    if not proof.get("ok"):
        return proof
    # Never invent a passing test result: it must be supplied by the runner
    # after executing actual tests. Missing test evidence stays missing.
    evidence = {**proof, **extra}
    if test_exit_code is not None:
        try:
            verified_exit_code = int(test_exit_code)
        except (TypeError, ValueError):
            return {**proof, "ok": False, "error": "invalid_test_exit_code"}
        evidence["test_results"] = {
            "exit_code": verified_exit_code,
            "ok": verified_exit_code == 0,
        }
        if verified_exit_code != 0:
            return {
                "ok": False, "error": "tests_failed",
                "evidence": evidence, "commit_sha": proof["commit_sha"],
            }
    return {"ok": True, "evidence": evidence, "commit_sha": proof["commit_sha"]}
