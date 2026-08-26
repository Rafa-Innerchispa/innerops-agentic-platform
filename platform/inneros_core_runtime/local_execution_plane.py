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
DEV_SWARM_GIT_USER_NAME = "RalfIA Dev Swarm"
DEV_SWARM_GIT_USER_EMAIL = "dev-swarm@inneros.local"

REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NESTED_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_PATTERN = re.compile(r"^(codex|chatgpt|cursor|antigravity|gemini|local-agent)/[A-Za-z0-9._/-]+$")
PROTECTED_BRANCHES = {"main", "master", "production", "prod", "develop"}
OWNER_APPROVED_GITHUB_OWNERS = {"Rafa-Innerchispa", "rafagye"}
OWNER_APPROVED_NESTED_REPOS = {"gitlab-community/gitlab-org/gitlab-runner"}
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
    "docs_git_markdown": [
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
        ("git", "log", "--oneline", "-n"),
    ],
    "go_gitlab_runner": [
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
        ("git", "log", "--oneline", "-n"),
        ("go", "version"),
        ("go", "test"),
        ("go", "build"),
        ("go", "vet"),
        ("make", "tools"),
        ("make", "development_setup"),
        ("make", "lint"),
        ("gofmt", "-l"),
        ("gofmt", "-d"),
        ("gofmt", "-w"),
        ("scripts/lint-docs",),
        ("scripts/lint-i18n-docs",),
        ("glab", "issue", "view"),
        ("glab", "issue", "list"),
        ("glab", "mr", "view"),
        ("glab", "mr", "list"),
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
    "Rafa-Innerchispa/inneros": {
        "profile": "python-tests",
        "source_path": "/home/rlopez/inneros/inneros_core",
        "allowed_paths": [
            "agents_pool",
            "config",
            "docs",
            "infra",
            "modules",
            "platform",
            "scripts",
            "services",
            "tenants",
        ],
    },
    "Rafa-Innerchispa/ralphiia-ecosystem-core": {
        "profile": "ecosystem-core-docs",
        "allowed_paths": ["bootstrap", "contracts", "docs", "ops", "registry", "runbooks"],
    },
    "Rafa-Innerchispa/ralfi-ia-platform": {
        "profile": "ecosystem-core-docs",
        "allowed_paths": ["companies", "docs"],
    },
    "Rafa-Innerchispa/innerspark-workforce-ai": {
        "profile": "node-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/innerspark-workforce-ai",
        "package_roots": ["services/femar-mvp-core"],
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
        "package_roots": ["."],
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


def _repo_name_allowed(repo: str) -> bool:
    return bool(REPO_PATTERN.match(repo or "") or repo in OWNER_APPROVED_NESTED_REPOS)


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


def _registry_repo_profiles() -> dict[str, dict[str, Any]]:
    try:
        from raphiia_openai import project_runtime_registry as prr

        data = prr._load()
    except Exception:
        return {}
    profiles: dict[str, dict[str, Any]] = {}
    for entry in (data.get("projects") or {}).values():
        repo = str(entry.get("repo") or "")
        if not _repo_name_allowed(repo):
            continue
        path = (entry.get("paths") or {}).get("primary") or ""
        try:
            safe = prr._safe_path(path)
        except Exception:
            continue
        detected_profile = "node-tests" if (safe / "package.json").exists() else "python-tests"
        registered_profile = str(entry.get("allowed_commands_profile") or "").strip()
        if registered_profile in {"python-tests", "node-tests"} and registered_profile != detected_profile:
            profile = detected_profile
        else:
            profile = registered_profile or detected_profile
        profiles[repo] = {
            "profile": profile,
            "source_path": str(safe),
            "allowed_paths": entry.get("allowed_paths") or OWNER_APPROVED_ALLOWED_PATHS,
            "package_roots": entry.get("package_roots") or ["."],
            "worktrees_path": str(_root() / "worktrees" / _slug(repo)),
            "project_id": entry.get("project_id"),
            "registry_backed": True,
        }
    return profiles


def _repo_config(repo: str) -> dict[str, Any]:
    if not _repo_name_allowed(repo or ""):
        raise ValueError("repo_must_be_owner_name")
    saved_env = {key: os.environ.get(key) for key in ("INNEROS_CORE_ROOT", "RALFIA_LOCAL_EXEC_ROOT")}
    owner_auto = _owner_approved_repo_config(repo)
    profiles = _load_repo_profiles()
    try:
        registry = _registry_repo_profiles()
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    if repo in profiles:
        conf = dict(profiles[repo])
    elif repo in registry:
        conf = dict(registry[repo])
    else:
        conf = owner_auto
        if not conf:
            raise PermissionError("repo_not_allowlisted")
    root = _root()
    conf.setdefault("profile", "python-tests")
    conf.setdefault("allowed_paths", ["."])
    conf.setdefault("package_roots", [])
    conf.setdefault("source_path", str(root / "repos" / _slug(repo)))
    conf.setdefault("worktrees_path", str(root / "worktrees" / _slug(repo)))
    return conf


def _owner_approved_repo_config(repo: str) -> dict[str, Any] | None:
    if repo in OWNER_APPROVED_NESTED_REPOS:
        core = Path(os.getenv("INNEROS_CORE_ROOT", str(DEFAULT_INNEROS_CORE_ROOT))).expanduser().resolve()
        source = (core / "workspaces" / "gitlab-runner").resolve()
        workspace_root = (core / "workspaces").resolve()
        if source != workspace_root and workspace_root not in source.parents:
            return None
        if not source.exists() or not (source / ".git").exists():
            return None
        return {
            "profile": "go_gitlab_runner",
            "source_path": str(source),
            "allowed_paths": ["docs/configuration/init.md", "README.md", "CONTRIBUTING.md", "AGENTS.md"],
            "package_roots": ["."],
            "worktrees_path": str(_root() / "worktrees" / _slug(repo)),
            "owner_approved_auto": True,
            "external_nested_fork": True,
        }
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
    known = DEFAULT_REPO_PROFILES.get(repo, {})
    profile = str(known.get("profile") or ("node-tests" if (source / "package.json").exists() else "python-tests"))
    return {
        "profile": profile,
        "source_path": str(source),
        "allowed_paths": list(known.get("allowed_paths") or OWNER_APPROVED_ALLOWED_PATHS),
        "package_roots": list(known.get("package_roots") or []),
        "owner_approved_auto": True,
        "repo_class": known.get("repo_class") or "owner-approved",
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


def _execution_env() -> dict[str, str]:
    env = dict(os.environ)
    path_parts = [
        "/home/rlopez/inneros/inneros_core/tools/go/bin",
        "/home/rlopez/.local/opt",
        "/home/rlopez/.local/bin",
        "/home/rlopez/.nvm/versions/node/v24.18.0/bin",
        "/home/rlopez/.nvm/versions/node/v20.20.2/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    existing = [part for part in path_parts if Path(part).exists()]
    current = env.get("PATH", "")
    env["PATH"] = ":".join([*existing, current] if current else existing)
    return env


def _run(argv: list[str], cwd: Path, *, timeout_seconds: int = 120, max_output_bytes: int = MAX_OUTPUT_BYTES_DEFAULT) -> dict[str, Any]:
    timeout = max(1, min(int(timeout_seconds or 120), MAX_TIMEOUT_SECONDS))
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        env=_execution_env(),
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


def _clean_package_root(root: str) -> str:
    rel = str(root or "").replace("\\", "/").strip().strip("/")
    if rel in {"", "."}:
        return "."
    if rel.startswith("/") or rel.startswith("../") or "/../" in rel or rel == "..":
        raise PermissionError("package_root_path_denied")
    parts = {part.lower() for part in rel.split("/") if part}
    if parts & DENIED_PATH_PARTS:
        raise PermissionError("package_root_path_denied")
    return rel


def _node_package_command_allowed(command: list[str], conf: dict[str, Any]) -> bool:
    if not command or command[0] != "npm":
        return False
    if any(re.search(r"[;&|`$<>]", part) for part in command):
        return False
    try:
        package_roots = {_clean_package_root(root) for root in (conf.get("package_roots") or [])}
    except PermissionError:
        return False
    if not package_roots:
        return False
    safe_actions = {"ci", "install"}
    package_root = "."
    action = ""
    if len(command) == 2 and command[1] in safe_actions:
        action = command[1]
    elif len(command) == 4 and command[1] == "--prefix" and command[3] in safe_actions:
        try:
            package_root = _clean_package_root(command[2])
        except PermissionError:
            return False
        action = command[3]
    elif len(command) == 4 and command[1] in safe_actions and command[2] == "--prefix":
        action = command[1]
        try:
            package_root = _clean_package_root(command[3])
        except PermissionError:
            return False
    else:
        return False
    return bool(action and package_root in package_roots)

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


def repo_policy_status(repo: str | None = None) -> dict[str, Any]:
    """Return effective repo policies, including registry-backed auto-onboarding."""
    try:
        profiles = _load_repo_profiles()
        registry = _registry_repo_profiles()
        profiles.update(registry)
        if repo:
            conf = _repo_config(repo)
            return {"ok": True, "capability": CAPABILITY, "repo": repo, "policy": conf, "registry_backed": bool(conf.get("registry_backed") or repo in registry)}
        return {
            "ok": True,
            "capability": CAPABILITY,
            "repo_count": len(profiles),
            "repos": sorted(profiles.keys()),
            "registry_backed": sorted(registry.keys()),
            "owner_auto_enroll": sorted(OWNER_APPROVED_GITHUB_OWNERS),
        }
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def repo_authorize(
    repo: str,
    repo_class: str = "product-app",
    write_scope: str = "worktree",
    allowed_paths: list[str] | None = None,
    allowed_commands_profile: str = "",
    package_roots: list[str] | None = None,
    approval_id: str = "",
    actor: str = "chatgpt",
    task_id: str = "",
    correlation_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Register an owner-approved repo in the Project Runtime Registry."""
    try:
        _require_metadata(actor, task_id or "manual", correlation_id or "manual")
        if not approval_id:
            raise ValueError("approval_id_required")
        owner, name = repo.split("/", 1)
        if owner not in OWNER_APPROVED_GITHUB_OWNERS and repo not in OWNER_APPROVED_NESTED_REPOS:
            raise PermissionError("repo_owner_not_allowlisted")
        project_id = repo.rsplit("/", 1)[1] if repo in OWNER_APPROVED_NESTED_REPOS else name
        source = Path(os.getenv("INNEROS_CORE_ROOT", str(DEFAULT_INNEROS_CORE_ROOT))).expanduser().resolve() / "workspaces" / project_id
        payload = {
            "repo": repo,
            "project_id": project_id,
            "project_path": str(source),
            "repo_class": repo_class,
            "write_scope": write_scope,
            "allowed_paths": allowed_paths or OWNER_APPROVED_ALLOWED_PATHS,
            "allowed_commands_profile": allowed_commands_profile,
            "package_roots": package_roots or ["."],
        }
        if dry_run:
            return {"ok": True, "dry_run": True, "would_register": payload}
        from raphiia_openai import project_runtime_registry as prr

        reg = prr.register_project(
            project_id,
            repo,
            str(source),
            actor=actor,
            source="repo_authorize",
            policy_class=repo_class,
            write_scope=write_scope,
            allowed_paths=allowed_paths or OWNER_APPROVED_ALLOWED_PATHS,
            allowed_commands_profile=allowed_commands_profile,
            package_roots=package_roots or ["."],
        )
        return {"ok": bool(reg.get("ok")), "registered": reg, "policy": payload}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def repo_revoke(
    repo: str,
    approval_id: str,
    actor: str = "chatgpt",
    task_id: str = "",
    correlation_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Revoke explicit write policy. Owner read-only auto-enroll remains."""
    try:
        if not approval_id:
            raise ValueError("approval_id_required")
        if dry_run:
            return {"ok": True, "dry_run": True, "would_revoke": repo}
        from raphiia_openai import project_runtime_registry as prr

        data = prr._load()
        for entry in (data.get("projects") or {}).values():
            if entry.get("repo") == repo:
                entry["write_scope"] = "read-only"
                entry["updated_at"] = _now_iso()
                entry["updated_by"] = actor
        prr._save(data)
        return {"ok": True, "repo": repo, "write_scope": "read-only"}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


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
            return {
                "ok": bool(status.get("ok") and (worktree / ".git").exists()),
                "idempotent": True,
                "repo": repo,
                "work_branch": work_branch,
                "worktree": str(worktree),
                "status": status,
                "verified_exists": (worktree / ".git").exists(),
            }
        add_cmd = ["git", "worktree", "add", "-b", work_branch, str(worktree), base_branch]
        result = _run(add_cmd, source, timeout_seconds=120)
        if not result.get("ok") and "already exists" in (result.get("stderr") or ""):
            result = _run(["git", "worktree", "add", str(worktree), work_branch], source, timeout_seconds=120)
        status = _run(["git", "status", "--short", "--branch"], worktree, timeout_seconds=30) if worktree.exists() else {"ok": False, "error": "worktree_path_missing"}
        exists = worktree.exists() and (worktree / ".git").exists()
        return {
            "ok": bool(result.get("ok") and exists and status.get("ok")),
            "repo": repo,
            "base_branch": base_branch,
            "work_branch": work_branch,
            "worktree": str(worktree),
            "result": result,
            "status": status,
            "verified_exists": exists,
        }
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


def _command_run_id(repo: str, work_branch: str, command: list[str], actor: str, task_id: str, correlation_id: str) -> str:
    raw = json.dumps(
        {
            "repo": repo,
            "work_branch": work_branch,
            "command": command,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": correlation_id,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _record_command_run(command_run_id: str, payload: dict[str, Any]) -> None:
    try:
        from raphiia_openai import mongo_store

        mongo_store.get_db()["ralfia_local_exec_command_runs"].update_one(
            {"command_run_id": command_run_id},
            {"$set": {**payload, "updated_at": _now_iso()}, "$setOnInsert": {"created_at": _now_iso()}},
            upsert=True,
        )
    except Exception:
        pass


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
    command_run_id = _command_run_id(repo, work_branch, command, actor, task_id, correlation_id)
    try:
        _require_metadata(actor, task_id, correlation_id)
        _validate_branch(work_branch, require_work_branch=True)
        conf = _repo_config(repo)
        profile = str(conf.get("profile") or "python-tests")
        if not (_command_allowed(command, profile) or (profile == "node-tests" and _node_package_command_allowed(command, conf))):
            return {"ok": False, "error": "command_not_allowlisted", "profile": profile, "command": command, "command_run_id": command_run_id}
        worktree = _worktree_path(repo, work_branch, conf)
        if not worktree.exists():
            return {"ok": False, "error": "worktree_missing", "worktree": str(worktree), "command_run_id": command_run_id}
        _record_command_run(
            command_run_id,
            {
                "status": "running",
                "repo": repo,
                "work_branch": work_branch,
                "profile": profile,
                "command": command,
                "actor": actor,
                "task_id": task_id,
                "correlation_id": correlation_id,
                "timeout_seconds": max(1, min(int(timeout_seconds or 120), MAX_TIMEOUT_SECONDS)),
            },
        )
        command_result = _run(command, worktree, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes)
        _record_command_run(
            command_run_id,
            {
                "status": "completed" if command_result.get("ok") else "failed",
                "repo": repo,
                "work_branch": work_branch,
                "profile": profile,
                "command": command,
                "actor": actor,
                "task_id": task_id,
                "correlation_id": correlation_id,
                "command_result": command_result,
            },
        )
        return {"ok": True, "profile": profile, "command_run_id": command_run_id, "command_result": command_result}
    except Exception as exc:
        _record_command_run(command_run_id, {"status": "error", "repo": repo, "work_branch": work_branch, "command": command, "actor": actor, "task_id": task_id, "correlation_id": correlation_id, "error": str(exc)})
        return {"ok": False, "capability": CAPABILITY, "error": str(exc), "command_run_id": command_run_id}


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
        commit = _run([
            "git",
            "-c",
            f"user.name={DEV_SWARM_GIT_USER_NAME}",
            "-c",
            f"user.email={DEV_SWARM_GIT_USER_EMAIL}",
            "commit",
            "-m",
            env_message,
        ], worktree, timeout_seconds=120)
        head = _run(["git", "rev-parse", "--short", "HEAD"], worktree, timeout_seconds=30)
        return {"ok": commit["ok"], "commit": commit, "head": (head.get("stdout") or "").strip(), "status_before": status}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def push_branch(
    repo: str,
    work_branch: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    idempotency_key: str,
    remote: str = "origin",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Push a validated work branch to its configured remote without force."""
    try:
        _require_metadata(actor, task_id, correlation_id, idempotency_key)
        _validate_branch(work_branch, require_work_branch=True)
        remote_name = (remote or "origin").strip()
        if not re.match(r"^[A-Za-z0-9_.-]{1,40}$", remote_name):
            return {"ok": False, "error": "remote_not_allowlisted"}
        conf = _repo_config(repo)
        worktree = _worktree_path(repo, work_branch, conf)
        if not worktree.exists():
            return {"ok": False, "error": "worktree_missing", "worktree": str(worktree)}
        current = _run(["git", "branch", "--show-current"], worktree, timeout_seconds=30)
        if (current.get("stdout") or "").strip() != work_branch:
            return {"ok": False, "error": "worktree_branch_mismatch", "current": current}
        status = _run(["git", "status", "--porcelain"], worktree, timeout_seconds=30)
        if (status.get("stdout") or "").strip():
            return {"ok": False, "error": "worktree_has_uncommitted_changes", "status": status}
        command = ["git", "push", remote_name, f"HEAD:refs/heads/{work_branch}"]
        if dry_run:
            remote_v = _run(["git", "remote", "-v"], worktree, timeout_seconds=30)
            head = _run(["git", "rev-parse", "--short", "HEAD"], worktree, timeout_seconds=30)
            return {"ok": True, "dry_run": True, "would_execute": command, "remote": remote_v, "head": (head.get("stdout") or "").strip()}
        push = _run(command, worktree, timeout_seconds=300)
        head = _run(["git", "rev-parse", "--short", "HEAD"], worktree, timeout_seconds=30)
        return {"ok": push["ok"], "push": push, "head": (head.get("stdout") or "").strip(), "remote": remote_name, "branch": work_branch}
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


def dev_swarm_scope_status(repo: str | None = None) -> dict[str, Any]:
    """Describe the bounded dev-swarm launcher surface available without admin scope."""
    policy = repo_policy_status(repo=repo)
    return {
        "ok": bool(policy.get("ok")),
        "capability": "dev_swarm_scope",
        "admin_scope_required": False,
        "required_scope": "ralfia:agents",
        "normal_flow": [
            "inspect repo policy",
            "prepare/fetch owner-approved repo",
            "acquire RACB repo lock",
            "create isolated worktree on chatgpt/*, codex/* or local-agent/* branch",
            "run allowlisted tests/build/status commands only",
            "write/apply bounded files or patches under allowed paths",
            "commit work branch and optionally push non-protected branch",
            "report evidence and continuity checkpoint",
        ],
        "denied": [
            "arbitrary shell",
            "secret paths and generated dependency folders",
            "direct edits to protected branches",
            "force push",
            "destructive delete/wipe/format",
            "repos outside owner-approved policy",
        ],
        "policy": policy,
        "tools": [
            "dev_swarm_launch_task",
            "local_exec_inspect_repo",
            "local_exec_prepare_repo",
            "local_exec_acquire_lock",
            "local_exec_create_worktree",
            "local_exec_write_file",
            "local_exec_apply_patch",
            "local_exec_run_command_allowlisted",
            "local_exec_commit_branch",
            "local_exec_push_branch",
            "local_exec_report_evidence",
            "codex_continuity_checkpoint",
        ],
    }


def dev_swarm_launch_task(
    repo: str,
    objective: str,
    base_branch: str = "main",
    work_branch: str = "",
    actor: str = "chatgpt",
    task_id: str = "",
    correlation_id: str = "",
    idempotency_key: str = "",
    remote_url: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Prepare the safe local development lane for a repo without ralfia:admin."""
    try:
        _require_metadata(actor, task_id, correlation_id, idempotency_key)
        if not (objective or "").strip():
            raise ValueError("objective_required")
        conf = _repo_config(repo)
        branch = work_branch.strip() or f"{actor}/{re.sub(r'[^A-Za-z0-9_.-]+', '-', task_id)[:48]}"
        _validate_branch(base_branch, allow_protected=True)
        _validate_branch(branch, require_work_branch=True)
        plan = {
            "repo": repo,
            "objective": objective,
            "base_branch": base_branch,
            "work_branch": branch,
            "actor": actor,
            "task_id": task_id,
            "correlation_id": correlation_id,
            "profile": conf.get("profile"),
            "allowed_paths": conf.get("allowed_paths"),
            "source_path": conf.get("source_path"),
            "admin_scope_required": False,
            "required_scope": "ralfia:agents",
            "checkout_or_pull": False,
            "next_actions": [
                "Use local_exec_write_file/apply_patch for bounded edits.",
                "Use local_exec_run_command_allowlisted for tests/build/status.",
                "Use local_exec_commit_branch and local_exec_report_evidence.",
                "Call codex_continuity_checkpoint before session/budget exhaustion.",
            ],
        }
        if dry_run:
            return {"ok": True, "dry_run": True, "capability": "dev_swarm_scope", "plan": plan}
        source = Path(str(conf.get("source_path") or "")).expanduser().resolve()
        prepared = {
            "ok": source.exists() and (source / ".git").exists(),
            "repo": repo,
            "source_path": str(source),
            "checkout_or_pull": False,
            "fetch_once": False,
        }
        if not prepared["ok"]:
            return {"ok": False, "stage": "source_repo_required", "plan": plan, "prepared": prepared}
        lock = acquire_lock(repo, actor, task_id, correlation_id, ttl_seconds=3600)
        if not lock.get("ok"):
            return {"ok": False, "stage": "acquire_lock", "plan": plan, "prepared": prepared, "lock": lock}
        worktree = create_worktree(repo, base_branch, branch, actor, task_id, correlation_id, idempotency_key)
        evidence = {
            "launcher": "dev_swarm_launch_task",
            "objective": objective,
            "prepared_ok": bool(prepared.get("ok")),
            "lock_ok": bool(lock.get("ok")),
            "worktree_ok": bool(worktree.get("ok")),
            "work_branch": branch,
            "source_path": conf.get("source_path"),
        }
        report = report_evidence(repo, branch, actor, task_id, correlation_id, "launched" if worktree.get("ok") else "launch_failed", evidence)
        return {
            "ok": bool(worktree.get("ok")),
            "capability": "dev_swarm_scope",
            "plan": plan,
            "prepared": prepared,
            "lock": lock,
            "worktree": worktree,
            "evidence": report,
        }
    except Exception as exc:
        return {"ok": False, "capability": "dev_swarm_scope", "error": str(exc)}


# Aliases MCP / AG-45 (nombres expuestos en catálogo)
local_exec_inspect_repo = inspect_repo
local_exec_repo_policy_status = repo_policy_status
local_exec_repo_authorize = repo_authorize
local_exec_repo_revoke = repo_revoke
local_exec_acquire_lock = acquire_lock
local_exec_release_lock = release_lock
local_exec_create_worktree = create_worktree
local_exec_apply_patch = apply_patch
local_exec_write_file = write_file
local_exec_run_command_allowlisted = run_command_allowlisted
local_exec_commit_branch = commit_branch
local_exec_push_branch = push_branch
local_exec_report_evidence = report_evidence
dev_swarm_scope_status = dev_swarm_scope_status
dev_swarm_launch_task = dev_swarm_launch_task


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
