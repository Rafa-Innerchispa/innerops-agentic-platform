"""Bridge Temporal agent candidacy to the bounded local execution plane.

Local models may only produce plans; this module materializes an isolated worktree,
applies allowlisted verification commands, and returns real diff/test evidence.
"""
from __future__ import annotations

import logging
import os
import re
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

GENERATED_PATH_PARTS = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".hypothesis",
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


def _normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").strip()


def _is_generated_or_cache_path(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    if not normalized or normalized.endswith("/"):
        return True
    parts = normalized.split("/")
    if any(part in GENERATED_PATH_PARTS for part in parts):
        return True
    return normalized.endswith((".pyc", ".pyo", ".swp", ".tmp"))


def _expand_path_entry(worktree: Path, entry: str) -> list[str]:
    normalized = _normalize_repo_path(entry)
    if not normalized:
        return []
    candidate = worktree / normalized
    if candidate.is_dir():
        return sorted(
            _normalize_repo_path(str(path.relative_to(worktree)))
            for path in candidate.rglob("*")
            if path.is_file() and not _is_generated_or_cache_path(str(path.relative_to(worktree)))
        )
    if candidate.is_file():
        return [normalized]
    return [normalized]


def _collect_unique_paths(worktree: Path, entries: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for entry in entries:
        for path in _expand_path_entry(worktree, entry):
            if _is_generated_or_cache_path(path):
                continue
            if path not in seen:
                seen.add(path)
                out.append(path)
    return sorted(out)


def _changed_paths(worktree: Path) -> list[str]:
    if not (worktree / ".git").exists() and not (worktree / ".git").is_file():
        raw = [
            str(p.relative_to(worktree)).replace("\\", "/")
            for p in worktree.rglob("*")
            if p.is_file() and ".git" not in p.parts
        ]
        return _collect_unique_paths(worktree, raw)
    try:
        names = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=60,
        )
        tracked = [line.strip() for line in (names.stdout or "").splitlines() if line.strip()]
        status = subprocess.run(
            ["git", "status", "--porcelain=1", "-uall"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=60,
        )
        status_paths: list[str] = []
        for line in (status.stdout or "").splitlines():
            if len(line) < 4:
                continue
            entry = line[3:].strip()
            if " -> " in entry:
                entry = entry.split(" -> ", 1)[1].strip()
            status_paths.append(entry)
        return _collect_unique_paths(worktree, tracked + status_paths)
    except Exception as exc:
        logger.warning("changed paths failed: %s", exc)
        return []


def _is_bridge_artifact_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if normalized.startswith("platform/"):
        normalized = normalized[len("platform/") :]
    for rel in BRIDGE_ARTIFACTS:
        if normalized == rel or normalized.endswith(f"/{rel}"):
            return True
        if Path(normalized).name == Path(rel).name and "temporal_" in normalized:
            return True
    return False


def objective_change_count(worktree: Path) -> Tuple[int, list[str], list[str]]:
    """Count changed files excluding Temporal bridge artifact copies (not task objective)."""
    paths = _changed_paths(worktree)
    bridge = [p for p in paths if _is_bridge_artifact_path(p)]
    objective = [p for p in paths if not _is_bridge_artifact_path(p)]
    return len(objective), objective, bridge


def _parse_required_objective_paths(envelope_dict: Dict[str, Any]) -> list[str]:
    required: set[str] = set()
    for raw in envelope_dict.get("required_objective_paths") or []:
        if str(raw).strip():
            required.add(_normalize_repo_path(str(raw)))
    texts: list[str] = [
        str(envelope_dict.get("objective") or ""),
        str(envelope_dict.get("title") or ""),
    ]
    texts.extend(str(item) for item in (envelope_dict.get("checklist") or []))
    for text in texts:
        lowered = text.lower()
        if "temporal_canary.md" in lowered:
            required.add("docs/TEMPORAL_CANARY.md")
        for match in re.finditer(r"`((?:docs|tests|src)/[^`\s]+)`", text, flags=re.IGNORECASE):
            required.add(_normalize_repo_path(match.group(1)))
        for match in re.finditer(
            r"\b((?:docs|src)/[\w./_-]+\.(?:md|py|json|yaml|yml|ts|tsx|js))\b",
            text,
            flags=re.IGNORECASE,
        ):
            required.add(_normalize_repo_path(match.group(1)))
    return sorted(path for path in required if path and not _is_generated_or_cache_path(path))


def _apply_required_objective_markers(envelope_dict: Dict[str, Any], worktree: Path) -> list[str]:
    """Deterministic bounded writes for explicit checklist markers (not free-form LLM edits)."""
    written: list[str] = []
    task_id = str(envelope_dict.get("task_id") or "")
    correlation_id = str(envelope_dict.get("correlation_id") or "")
    for rel in _parse_required_objective_paths(envelope_dict):
        if rel.lower() != "docs/temporal_canary.md":
            continue
        dest = worktree / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        body = (
            "# TEMPORAL CANARY\n\n"
            f"task_id={task_id}\n"
            f"correlation_id={correlation_id}\n"
            "marker=persistent_temporal_canary\n"
        )
        dest.write_text(body, encoding="utf-8")
        written.append(rel)
    return written


def _objective_diff_excerpt(worktree: Path, objective_paths: list[str]) -> str:
    lines: list[str] = []
    for rel in objective_paths[:25]:
        path = worktree / rel
        if not path.is_file():
            continue
        snippet = path.read_text(encoding="utf-8", errors="replace").splitlines()[:8]
        lines.append(f"--- {rel}")
        lines.extend(f"+ {line}" for line in snippet)
    return "\n".join(lines)[:8000]


def _git_diff_summary(worktree: Path, objective_paths: list[str] | None = None) -> Tuple[int, str]:
    objective_paths = objective_paths or []
    if not (worktree / ".git").exists() and not (worktree / ".git").is_file():
        files = _changed_paths(worktree)
        _, objective, _ = objective_change_count(worktree)
        excerpt = _objective_diff_excerpt(worktree, objective or objective_paths)
        return len(objective), excerpt or f"+ {len(files)} files in worktree (non-git)"
    try:
        stat = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=60,
        )
        _, objective, _ = objective_change_count(worktree)
        diff_text = (stat.stdout or "").strip()
        excerpt = _objective_diff_excerpt(worktree, objective or objective_paths)
        if excerpt:
            diff_text = (diff_text + "\n\n" + excerpt).strip() if diff_text else excerpt
        if not diff_text and objective:
            diff_text = "\n".join(f"+ {path}" for path in objective[:50])
        return len(objective), diff_text[:8000]
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

    sync_bridge = bool(envelope_dict.get("sync_bridge_artifacts", True))
    touched = sync_bridge_artifacts(wt_path) if repo and sync_bridge else []
    marker_writes = _apply_required_objective_markers(envelope_dict, wt_path)
    required_objective = _parse_required_objective_paths(envelope_dict)
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

    objective_count, objective_paths, bridge_paths = objective_change_count(wt_path)
    files_count, code_diff = _git_diff_summary(wt_path, objective_paths)
    missing_required = [
        rel for rel in required_objective if not (wt_path / rel).is_file()
    ]
    satisfied_required = [
        rel for rel in required_objective if rel in objective_paths and (wt_path / rel).is_file()
    ]

    ok = bool(test_results.get("ok"))
    if task_class == "coding" and ok and objective_count == 0:
        ok = False
        test_results["reason"] = "coding_task_requires_non_bridge_objective_diff"
    if task_class == "coding" and ok and required_objective and missing_required:
        ok = False
        test_results["reason"] = "required_objective_paths_missing"
        test_results["missing_required_objective_paths"] = missing_required
    if task_class == "coding" and ok and required_objective and not satisfied_required:
        ok = False
        test_results["reason"] = "required_objective_not_in_objective_diff"
        test_results["required_objective_paths"] = required_objective
        test_results["objective_paths"] = objective_paths
    if task_class == "coding" and ok and files_count == 0 and not code_diff and objective_count == 0:
        ok = False
        test_results["reason"] = "coding_task_requires_diff_or_files"

    return {
        "ok": ok,
        "files_count": files_count,
        "objective_files_count": objective_count,
        "objective_paths": objective_paths[:50],
        "required_objective_paths": required_objective[:50],
        "objective_marker_writes": marker_writes,
        "missing_required_objective_paths": missing_required,
        "bridge_artifact_paths": bridge_paths[:50],
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
