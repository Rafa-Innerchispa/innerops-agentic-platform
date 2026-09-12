"""Read-only Git alignment evidence for Project Runtime Registry."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _probe(path: Path, args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(path),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def alignment_status(project_path: str, repo: str) -> dict[str, Any]:
    """Prove whether the physical checkout is the same clean SHA as origin/main.

    This function is intentionally read-only and does not fetch. A stale
    ``origin/main`` is therefore visible instead of being silently repaired.
    Explicit reconciliation/bootstrap code owns network mutation.
    """
    path = Path(project_path)
    if not (path / ".git").exists():
        return {"ok": False, "reason": "not_a_git_checkout", "aligned_with_origin_main": False}
    try:
        branch_p = _probe(path, ["branch", "--show-current"])
        local_p = _probe(path, ["rev-parse", "HEAD"])
        remote_p = _probe(path, ["rev-parse", "--verify", "origin/main^{commit}"])
        status_p = _probe(path, ["status", "--porcelain"])
        origin_p = _probe(path, ["remote", "get-url", "origin"])
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "reason": f"git_probe_failed:{type(exc).__name__}",
            "aligned_with_origin_main": False,
        }

    branch = (branch_p.stdout or "").strip()
    local_head = (local_p.stdout or "").strip()
    origin_main = (remote_p.stdout or "").strip()
    dirty = bool((status_p.stdout or "").strip()) or status_p.returncode != 0
    origin_url = (origin_p.stdout or "").strip()
    repo_path = str(repo or "").strip().removesuffix(".git")
    expected_https = f"https://github.com/{repo_path}"
    expected_ssh = f"git@github.com:{repo_path}"
    normalized_origin = origin_url.removesuffix(".git")
    remote_matches = normalized_origin in {expected_https, expected_ssh}
    aligned = bool(local_head and origin_main and local_head == origin_main and not dirty and remote_matches)

    if not remote_matches:
        reason = "origin_remote_mismatch"
    elif dirty:
        reason = "working_tree_dirty"
    elif not origin_main:
        reason = "origin_main_unresolved"
    elif local_head != origin_main:
        reason = "local_head_differs_from_origin_main"
    else:
        reason = "aligned"

    return {
        "ok": all(p.returncode == 0 for p in (branch_p, local_p, status_p, origin_p)) and bool(local_head),
        "branch": branch,
        "local_head": local_head,
        "origin_main": origin_main,
        "dirty": dirty,
        "remote_matches_repo": remote_matches,
        "aligned_with_origin_main": aligned,
        "reason": reason,
    }
