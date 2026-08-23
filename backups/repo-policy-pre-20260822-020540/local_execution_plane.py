"""Safe local repository execution plane for Ralphi IA.

This module is intentionally boring: no shell strings, no privileged commands,
no production deploys, no secrets, and no edits outside isolated worktrees.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAPABILITY = "local_execution_plane"
DEFAULT_INNEROS_CORE_ROOT = Path("/home/rlopez/inneros/inneros_core")
DEFAULT_ROOT = DEFAULT_INNEROS_CORE_ROOT / "var" / "local_execution"
MAX_OUTPUT_BYTES_DEFAULT = 60000
MAX_TIMEOUT_SECONDS = 1200

REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_PATTERN = re.compile(r"^(codex|chatgpt|cursor|antigravity|gemini|local-agent)/[A-Za-z0-9._/-]+$")
PROTECTED_BRANCHES = {"main", "master", "production", "prod", "develop"}
OWNER_APPROVED_GITHUB_OWNERS = {"Rafa-Innerchispa"}
OWNER_APPROVED_ALLOWED_PATHS = [
    "app",
    "components",
    "docs",
    "infra",
    "lib",
    "modules",
    "public",
    "scripts",
    "src",
    "tests",
    "AGENT_CONTRACT.md",
    "BASELINE_PROVENANCE.md",
    "DEPLOYMENT.md",
    "README.md",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "requirements.txt",
    "tsconfig.json",
    "next.config.js",
    "next.config.mjs",
    "vite.config.ts",
]
DENIED_PATH_PARTS = {
    ".env",
    ".ssh",
    ".gnupg",
    "secrets",
    "secret",
    "backup",
    "backups",
    "dump",
    "dumps",
    "private",
    "credentials",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|private[_-]?key)\s*[:=]\s*[^\s]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[opsu]_[A-Za-z0-9_]{20,}"),
]

ALLOWLISTED_COMMANDS: dict[str, list[tuple[str, ...]]] = {
    "ecosystem-core-docs": [
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
        ("git", "log", "--oneline", "-n"),
        ("python", "-m", "json.tool"),
        ("python3", "-m", "json.tool"),
    ],
    "python-tests": [
        ("python", "-m", "pytest"),
        ("python3", "-m", "pytest"),
        ("pytest",),
        ("python", "-m", "compileall"),
        ("python3", "-m", "compileall"),
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
    ],
    "node-tests": [
        ("npm", "test"),
        ("npm", "run", "test"),
        ("npm", "run", "lint"),
        ("npm", "run", "build"),
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
    ],
}

DEFAULT_REPO_PROFILES = {
    "Rafa-Innerchispa/ralphiia-ecosystem-core": {
        "profile": "ecosystem-core-docs",
        "allowed_paths": ["bootstrap", "contracts", "docs", "ops", "registry", "runbooks"],
    },
    "Rafa-Innerchispa/ralfi-ia-platform": {
        "profile": "ecosystem-core-docs",
        "allowed_paths": ["companies", "docs"],
    },
    "Rafa-Innerchispa/inneros-core": {
        "profile": "python-tests",
        "allowed_paths": [
            "platform/raphiia_openai",
            "platform/scripts",
            "platform/services/swarm_os",
        ],
        "source_path": "/home/rlopez/inneros/inneros_core",
    },
    "Rafa-Innerchispa/inneros": {
        "profile": "python-tests",
        "allowed_paths": ["."],
        "source_path": "/home/rlopez/inneros/inneros_core",
    },
    "Rafa-Innerchispa/innerspark-workforce-ai": {
        "profile": "node-tests",
        "source_path": "/home/rlopez/projects/innerspark-workforce-ai",
        "allowed_paths": [
            "app",
            "components",
            "docs",
            "lib",
            "public",
            "scripts",
            "src",
            "tests",
            "README.md",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "tsconfig.json",
            "next.config.js",
            "next.config.mjs",
            "vite.config.ts",
        ],
    },
    "Rafa-Innerchispa/innerops-agentic-platform": {
        "profile": "node-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform",
        "allowed_paths": [
            "app",
            "components",
            "docs",
            "lib",
            "public",
            "scripts",
            "src",
            "tests",
            "BASELINE_PROVENANCE.md",
            "AGENT_CONTRACT.md",
            "DEPLOYMENT.md",
            "README.md",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "tsconfig.json",
            "next.config.js",
            "next.config.mjs",
            "vite.config.ts",
        ],
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: str) -> str:
    redacted = value or ""
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: m.group(0).split("=", 1)[0].split(":", 1)[0] + "=[REDACTED]", redacted)
    return redacted


def _bounded_output(text: str, max_bytes: int) -> str:
    raw = _redact(text or "")
    encoded = raw.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return raw
    return encoded[:max_bytes].decode("utf-8", errors="replace") + "\n[TRUNCATED]"


def _slug(repo: str) -> str:
    return repo.replace("/", "__")


def _root() -> Path:
    configured_root = os.getenv("RALFIA_LOCAL_EXEC_ROOT", "").strip()
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    inneros_core = Path(os.getenv("INNEROS_CORE_ROOT", str(DEFAULT_INNEROS_CORE_ROOT))).expanduser()
    return (inneros_core / "var" / "local_execution").resolve()


def _load_repo_profiles() -> dict[str, dict[str, Any]]:
    raw = os.getenv("RALFIA_LOCAL_EXEC_REPOS_JSON", "").strip()
    profiles = dict(DEFAULT_REPO_PROFILES)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                profiles.update(parsed)
        except json.JSONDecodeError:
            pass
    return profiles


def _repo_config(repo: str) -> dict[str, Any]:
    if not REPO_PATTERN.match(repo or ""):
        raise ValueError("repo_must_be_owner_name")
    profiles = _load_repo_profiles()
    if repo in profiles:
        conf = dict(profiles[repo])
    else:
        conf = _owner_approved_repo_config(repo)
        if not conf:
            raise PermissionError("repo_not_allowlisted")
    root = _root()
    conf.setdefault("profile", "python-tests")
    conf.setdefault("allowed_paths", ["."])
    conf.setdefault("source_path", str(root / "repos" / _slug(repo)))
    conf.setdefault("worktrees_path", str(root / "worktrees" / _slug(repo)))
    return conf


def _owner_approved_repo_config(repo: str) -> dict[str, Any] | None:
    owner, name = repo.split("/", 1)
    if owner not in OWNER_APPROVED_GITHUB_OWNERS:
        return None
    core = Path(os.getenv("INNEROS_CORE_ROOT", str(DEFAULT_INNEROS_CORE_ROOT))).expanduser().resolve()
    source = (core / "workspaces" / name).resolve()
    workspace_root = (core / "workspaces").resolve()
    if source != workspace_root and workspace_root not in source.parents:
        return None
    if not source.exists() or not (source / ".git").exists():
        return None
    profile = "node-tests" if (source / "package.json").exists() else "python-tests"
    return {
        "profile": profile,
        "source_path": str(source),
        "allowed_paths": OWNER_APPROVED_ALLOWED_PATHS,
        "owner_approved_auto": True,
    }


def _resolve_under(base: Path, path: str | Path) -> Path:
    base_r = base.resolve()
    target = (base_r / path).resolve()
    if target != base_r and base_r not in target.parents:
        raise PermissionError("path_outside_workspace")
    return target


def _validate_relative_path(path: str, allowed_paths: list[str]) -> str:
    rel = (path or "").replace("\\", "/").strip("/")
    if not rel or rel.startswith("../") or "/../" in rel or rel == "..":
        raise PermissionError("path_traversal_denied")
    parts = {part.lower() for part in rel.split("/") if part}
    if parts & DENIED_PATH_PARTS:
        raise PermissionError("secret_or_generated_path_denied")
    allowed = [p.strip("/").replace("\\", "/") for p in allowed_paths or ["."]]
    if "." not in allowed and not any(rel == prefix or rel.startswith(prefix + "/") for prefix in allowed):
        raise PermissionError("path_not_allowed_for_repo_profile")
    return rel


def _validate_branch(branch: str, *, require_work_branch: bool = False, allow_protected: bool = False) -> str:
    value = (branch or "").strip()
    if not value:
        raise ValueError("branch_required")
    if value in PROTECTED_BRANCHES and not allow_protected:
        raise PermissionError("protected_branch_denied")
    if require_work_branch and not BRANCH_PATTERN.match(value):
        raise PermissionError("work_branch_prefix_denied")
    return value


def _require_metadata(actor: str, task_id: str, correlation_id: str, idempotency_key: str | None = None) -> None:
    if not (actor or "").strip():
        raise ValueError("actor_required")
    if not (task_id or "").strip():
        raise ValueError("task_id_required")
    if not (correlation_id or "").strip():
        raise ValueError("correlation_id_required")
    if idempotency_key is not None and not idempotency_key.strip():
        raise ValueError("idempotency_key_required")


def _run(argv: list[str], cwd: Path, *, timeout_seconds: int = 120, max_output_bytes: int = MAX_OUTPUT_BYTES_DEFAULT) -> dict[str, Any]:
    timeout = max(1, min(int(timeout_seconds or 120), MAX_TIMEOUT_SECONDS))
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    stdout = _bounded_output(proc.stdout, max_output_bytes)
    stderr = _bounded_output(proc.stderr, max_output_bytes)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "argv": argv,
    }


def _command_allowed(command: list[str], profile: str) -> bool:
    if not command or any(not isinstance(part, str) or not part for part in command):
        return False
    if any(re.search(r"[;&|`$<>]", part) for part in command):
        return False
    allowed = ALLOWLISTED_COMMANDS.get(profile, [])
    for prefix in allowed:
        if tuple(command[: len(prefix)]) == prefix:
            return True
    return False


def _worktree_path(repo: str, work_branch: str, conf: dict[str, Any]) -> Path:
    branch_slug = re.sub(r"[^A-Za-z0-9_.-]+", "__", work_branch)
    return Path(conf["worktrees_path"]).expanduser().resolve() / branch_slug


def inspect_repo(repo: str) -> dict[str, Any]:
    """Return sanitized repo/worktree configuration and current Git status."""
    try:
        conf = _repo_config(repo)
        source = Path(conf["source_path"]).expanduser().resolve()
        worktrees = Path(conf["worktrees_path"]).expanduser().resolve()
        result: dict[str, Any] = {
            "ok": True,
            "capability": CAPABILITY,
            "repo": repo,
            "profile": conf["profile"],
            "allowed_paths": conf.get("allowed_paths", []),
            "source_exists": source.exists(),
            "source_path": str(source),
            "worktrees_path": str(worktrees),
            "tooling": {
                "requires_lock": True,
                "isolated_worktree_required": True,
                "arbitrary_shell": "denied",
                "protected_branch_direct_edits": "denied",
            },
        }
        if source.exists():
            result["git_status"] = _run(["git", "status", "--short", "--branch"], source, timeout_seconds=20)
            result["git_head"] = _run(["git", "rev-parse", "--short", "HEAD"], source, timeout_seconds=20)
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "repo": repo, "error": str(exc)}


def acquire_lock(repo: str, actor: str, task_id: str, correlation_id: str, ttl_seconds: int = 1800) -> dict[str, Any]:
    """Acquire a RACB lock for a repository before mutation."""
    try:
        _require_metadata(actor, task_id, correlation_id)
        _repo_config(repo)
        from raphiia_openai import racb_locks

        return racb_locks.manage_coordination_lock(
            action="acquire",
            resource_id=f"repo:{repo}",
            agent=actor,
            task_id=task_id,
            ttl_seconds=ttl_seconds,
        )
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def release_lock(repo: str, actor: str, task_id: str, correlation_id: str) -> dict[str, Any]:
    """Release a RACB repository lock."""
    try:
        _require_metadata(actor, task_id, correlation_id)
        _repo_config(repo)
        from raphiia_openai import racb_locks

        return racb_locks.manage_coordination_lock(
            action="release",
            resource_id=f"repo:{repo}",
            agent=actor,
            task_id=task_id,
        )
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def create_worktree(
    repo: str,
    base_branch: str,
    work_branch: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Create or reuse an isolated Git worktree for a safe work branch."""
    try:
        _require_metadata(actor, task_id, correlation_id, idempotency_key)
        _validate_branch(base_branch, allow_protected=True)
        _validate_branch(work_branch, require_work_branch=True)
        conf = _repo_config(repo)
        source = Path(conf["source_path"]).expanduser().resolve()
        worktree = _worktree_path(repo, work_branch, conf)
        if not source.exists():
            return {"ok": False, "error": "source_repo_missing", "source_path": str(source)}
        if not (source / ".git").exists():
            return {"ok": False, "error": "source_repo_not_git", "source_path": str(source)}
        worktree.parent.mkdir(parents=True, exist_ok=True)
        if worktree.exists():
            status = _run(["git", "status", "--short", "--branch"], worktree, timeout_seconds=30)
            return {"ok": True, "idempotent": True, "repo": repo, "work_branch": work_branch, "worktree": str(worktree), "status": status}
        result = _run(["git", "worktree", "add", "-b", work_branch, str(worktree), base_branch], source, timeout_seconds=120)
        return {"ok": result["ok"], "repo": repo, "base_branch": base_branch, "work_branch": work_branch, "worktree": str(worktree), "result": result}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def apply_patch(
    repo: str,
    work_branch: str,
    patch: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Apply a bounded unified diff in a worktree."""
    try:
        _require_metadata(actor, task_id, correlation_id, idempotency_key)
        _validate_branch(work_branch, require_work_branch=True)
        if not patch or len(patch.encode("utf-8")) > 200000:
            return {"ok": False, "error": "patch_missing_or_too_large"}
        conf = _repo_config(repo)
        worktree = _worktree_path(repo, work_branch, conf)
        if not worktree.exists():
            return {"ok": False, "error": "worktree_missing", "worktree": str(worktree)}
        denied = [part for part in DENIED_PATH_PARTS if re.search(rf"(^|/){re.escape(part)}($|/)", patch, re.I)]
        if denied:
            return {"ok": False, "error": "patch_mentions_denied_path", "denied": sorted(set(denied))}
        proc = subprocess.run(
            ["git", "apply", "--whitespace=fix", "-"],
            input=patch,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": _bounded_output(proc.stdout, MAX_OUTPUT_BYTES_DEFAULT),
            "stderr": _bounded_output(proc.stderr, MAX_OUTPUT_BYTES_DEFAULT),
        }
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def write_file(
    repo: str,
    work_branch: str,
    path: str,
    content: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Write one bounded file under allowed repo paths."""
    try:
        _require_metadata(actor, task_id, correlation_id, idempotency_key)
        _validate_branch(work_branch, require_work_branch=True)
        conf = _repo_config(repo)
        rel = _validate_relative_path(path, list(conf.get("allowed_paths") or ["."]))
        if len((content or "").encode("utf-8")) > 200000:
            return {"ok": False, "error": "content_too_large"}
        worktree = _worktree_path(repo, work_branch, conf)
        target = _resolve_under(worktree, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")
        return {"ok": True, "repo": repo, "work_branch": work_branch, "path": rel, "bytes": len((content or "").encode("utf-8"))}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def run_command_allowlisted(
    repo: str,
    work_branch: str,
    command: list[str],
    actor: str,
    task_id: str,
    correlation_id: str,
    timeout_seconds: int = 120,
    max_output_bytes: int = MAX_OUTPUT_BYTES_DEFAULT,
) -> dict[str, Any]:
    """Run a structurally allowlisted command in the isolated worktree."""
    try:
        _require_metadata(actor, task_id, correlation_id)
        _validate_branch(work_branch, require_work_branch=True)
        conf = _repo_config(repo)
        profile = str(conf.get("profile") or "python-tests")
        if not _command_allowed(command, profile):
            return {"ok": False, "error": "command_not_allowlisted", "profile": profile, "command": command}
        worktree = _worktree_path(repo, work_branch, conf)
        if not worktree.exists():
            return {"ok": False, "error": "worktree_missing", "worktree": str(worktree)}
        return {"ok": True, "profile": profile, "command_result": _run(command, worktree, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes)}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def commit_branch(
    repo: str,
    work_branch: str,
    message: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Commit current worktree changes on the work branch."""
    try:
        _require_metadata(actor, task_id, correlation_id, idempotency_key)
        _validate_branch(work_branch, require_work_branch=True)
        conf = _repo_config(repo)
        worktree = _worktree_path(repo, work_branch, conf)
        if not worktree.exists():
            return {"ok": False, "error": "worktree_missing", "worktree": str(worktree)}
        status = _run(["git", "status", "--short"], worktree, timeout_seconds=30)
        if not (status.get("stdout") or "").strip():
            return {"ok": True, "idempotent": True, "message": "nothing_to_commit", "status": status}
        _run(["git", "add", "-A"], worktree, timeout_seconds=60)
        env_message = (message or "").strip()[:200] or f"local exec {task_id}"
        commit = _run(["git", "commit", "-m", env_message], worktree, timeout_seconds=120)
        head = _run(["git", "rev-parse", "--short", "HEAD"], worktree, timeout_seconds=30)
        return {"ok": commit["ok"], "commit": commit, "head": (head.get("stdout") or "").strip(), "status_before": status}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def report_evidence(
    repo: str,
    work_branch: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    status: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a compact local execution evidence event in coordination log."""
    try:
        _require_metadata(actor, task_id, correlation_id)
        _repo_config(repo)
        payload = {
            "capability": CAPABILITY,
            "repo": repo,
            "work_branch": work_branch,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": correlation_id,
            "status": status,
            "evidence": evidence or {},
            "reported_at": _now_iso(),
            "evidence_hash": hashlib.sha256(json.dumps(evidence or {}, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16],
        }
        from raphiia_openai import mongo_store

        doc = mongo_store.log_coordination(
            agent=actor.upper(),
            summary=f"Local execution {status}: {repo} {work_branch}",
            event="local_execution",
            project="ralfia-local-execution-plane",
            tool_used="local_execution_plane.report_evidence",
            metadata=payload,
        )
        return {"ok": True, "reported": doc, "payload": payload}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


# Aliases MCP / AG-45 (nombres expuestos en catálogo)
local_exec_inspect_repo = inspect_repo
local_exec_acquire_lock = acquire_lock
local_exec_release_lock = release_lock
local_exec_create_worktree = create_worktree
local_exec_apply_patch = apply_patch
local_exec_write_file = write_file
local_exec_run_command_allowlisted = run_command_allowlisted
local_exec_commit_branch = commit_branch
local_exec_report_evidence = report_evidence


def prepare_repo(
    repo: str,
    base_ref: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    idempotency_key: str,
    remote_url: str | None = None,
) -> dict[str, Any]:
    """Clone/fetch allowlisted repo into local execution workspace."""
    try:
        _require_metadata(actor, task_id, correlation_id, idempotency_key)
        conf = _repo_config(repo)
        source = Path(conf["source_path"]).expanduser().resolve()
        source.parent.mkdir(parents=True, exist_ok=True)
        if source.exists() and (source / ".git").exists():
            fetch = _run(["git", "fetch", "--all", "--prune"], source, timeout_seconds=120)
            checkout = _run(["git", "checkout", base_ref], source, timeout_seconds=60)
            pull = _run(["git", "pull", "--ff-only"], source, timeout_seconds=120)
            return {
                "ok": fetch["ok"] and checkout["ok"],
                "repo": repo,
                "source_path": str(source),
                "idempotent": True,
                "fetch": fetch,
                "checkout": checkout,
                "pull": pull,
            }
        clone_url = (remote_url or "").strip()
        if not clone_url:
            return {"ok": False, "error": "source_repo_missing_and_no_remote_url", "source_path": str(source)}
        clone = _run(["git", "clone", "--branch", base_ref, clone_url, str(source)], source.parent, timeout_seconds=600)
        return {"ok": clone["ok"], "repo": repo, "source_path": str(source), "clone": clone}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


local_exec_prepare_repo = prepare_repo
local_exec_hydrate_repo = prepare_repo
