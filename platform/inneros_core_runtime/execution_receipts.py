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
