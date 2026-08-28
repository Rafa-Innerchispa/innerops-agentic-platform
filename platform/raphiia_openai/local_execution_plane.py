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

REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+){1,2}$")
GITLAB_COMMUNITY_RUNNER_REPO = "gitlab-community/gitlab-org/gitlab-runner"
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
OWNER_APPROVED_REPO_CLASSES = {
    "inneros": {
        "repo_class": "mcp-runtime",
        "profile": "python-tests",
        "allowed_paths": ["agents_pool", "config", "docs", "infra", "modules", "platform", "scripts", "services", "tenants"],
    },
    "ralphiia-ecosystem-core": {
        "repo_class": "canonical-core",
        "profile": "ecosystem-core-docs",
        "allowed_paths": ["bootstrap", "contracts", "docs", "ops", "registry", "runbooks"],
    },
    "ralphiia-founderos-openai": {
        "repo_class": "hackathon-product",
        "profile": "node-tests",
        "allowed_paths": OWNER_APPROVED_ALLOWED_PATHS,
    },
    "innerspark-workforce-ai": {
        "repo_class": "product-app",
        "profile": "node-tests",
        "allowed_paths": OWNER_APPROVED_ALLOWED_PATHS,
        "package_roots": ["services/femar-mvp-core"],
    },
    "innerops-agentic-platform": {
        "repo_class": "product-app",
        "profile": "node-tests",
        "allowed_paths": OWNER_APPROVED_ALLOWED_PATHS,
        "package_roots": ["."],
    },
    "gitlab-runner": {
        "repo_class": "external_fork_docs_only",
        "profile": "go_gitlab_runner",
        "allowed_paths": ["docs/configuration/init.md", "README.md", "CONTRIBUTING.md", "AGENTS.md"],
        "package_roots": [],
    },
}
REPO_POLICY_COLLECTION = "ralfia_local_exec_repo_policy"
REPO_POLICY_AUDIT_COLLECTION = "ralfia_local_exec_policy_audit"
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
    "go_gitlab_runner": [
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
        ("git", "log", "--oneline", "-n"),
        ("go", "version"),
        ("go", "test"),
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
    for repo, conf in list(profiles.items()):
        merged = _owner_approved_repo_config(repo) or {}
        merged.update(conf)
        profiles[repo] = merged
    try:
        from raphiia_openai import mongo_store

        for doc in mongo_store.get_db()[REPO_POLICY_COLLECTION].find({"status": "active"}):
            repo = str(doc.get("repo") or "")
            if not REPO_PATTERN.match(repo):
                continue
            profiles[repo] = _policy_doc_to_config(doc)
    except Exception:
        pass
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
    conf.setdefault("remote_url", f"https://github.com/{repo}.git")
    conf.setdefault("protected_branches", sorted(PROTECTED_BRANCHES))
    conf.setdefault("package_roots", [])
    conf.setdefault("requires_approval", True)
    conf.setdefault("write_scope", "worktree")
    conf.setdefault("status", "active")
    conf.setdefault("owner", repo.split("/", 1)[0])
    return conf


def _owner_approved_repo_config(repo: str) -> dict[str, Any] | None:
    owner, name = repo.split("/", 1)
    core = Path(os.getenv("INNEROS_CORE_ROOT", str(DEFAULT_INNEROS_CORE_ROOT))).expanduser().resolve()
    if repo == GITLAB_COMMUNITY_RUNNER_REPO:
        known = OWNER_APPROVED_REPO_CLASSES["gitlab-runner"]
        source = (core / "workspaces" / "gitlab-runner").resolve()
        return {
            "profile": known["profile"],
            "source_path": str(source),
            "allowed_paths": list(known["allowed_paths"]),
            "package_roots": [],
            "owner_approved_auto": True,
            "repo_class": known["repo_class"],
            "write_scope": "worktree",
            "requires_approval": True,
            "remote_url": "https://gitlab.com/gitlab-community/gitlab-org/gitlab-runner.git",
            "status": "active",
            "owner": owner,
            "external_nested_fork": True,
        }
    if owner not in OWNER_APPROVED_GITHUB_OWNERS:
        return None
    workspace_source = (core / "workspaces" / name).resolve()
    workspace_root = (core / "workspaces").resolve()
    if workspace_source != workspace_root and workspace_root not in workspace_source.parents:
        return None
    fallback_source = (_root() / "repos" / _slug(repo)).resolve()
    source = workspace_source if (workspace_source / ".git").exists() else fallback_source
    known = OWNER_APPROVED_REPO_CLASSES.get(name, {})
    profile = str(known.get("profile") or ("node-tests" if (source / "package.json").exists() else "python-tests"))
    write_scope = "worktree" if name in OWNER_APPROVED_REPO_CLASSES else "read_only"
    return {
        "profile": profile,
        "source_path": str(source),
        "allowed_paths": list(known.get("allowed_paths") or OWNER_APPROVED_ALLOWED_PATHS),
        "package_roots": list(known.get("package_roots") or []),
        "owner_approved_auto": True,
        "repo_class": known.get("repo_class") or "owner-approved-readonly",
        "write_scope": write_scope,
        "requires_approval": write_scope != "read_only",
        "remote_url": f"https://github.com/{repo}.git",
        "status": "auto_read_only" if write_scope == "read_only" else "active",
        "owner": owner,
    }


def _policy_doc_to_config(doc: dict[str, Any]) -> dict[str, Any]:
    repo = str(doc.get("repo") or "")
    owner, name = repo.split("/", 1)
    known = OWNER_APPROVED_REPO_CLASSES.get(name, {})
    return {
        "profile": doc.get("allowed_commands") or doc.get("profile") or known.get("profile") or "python-tests",
        "allowed_paths": list(doc.get("allowed_paths") or known.get("allowed_paths") or OWNER_APPROVED_ALLOWED_PATHS),
        "source_path": doc.get("source_path") or str((_root() / "repos" / _slug(repo)).resolve()),
        "worktrees_path": doc.get("worktrees_path") or str((_root() / "worktrees" / _slug(repo)).resolve()),
        "remote_url": doc.get("remote_url") or f"https://github.com/{repo}.git",
        "repo_class": doc.get("repo_class") or known.get("repo_class") or "owner-approved-readonly",
        "write_scope": doc.get("write_scope") or "read_only",
        "protected_branches": list(doc.get("protected_branches") or sorted(PROTECTED_BRANCHES)),
        "package_roots": list(doc.get("package_roots") or known.get("package_roots") or []),
        "requires_approval": bool(doc.get("requires_approval", True)),
        "owner": doc.get("owner") or owner,
        "status": doc.get("status") or "active",
        "policy_source": "mongo_registry",
        "last_verified": doc.get("last_verified"),
    }


def _write_allowed(conf: dict[str, Any]) -> bool:
    return str(conf.get("write_scope") or "read_only") in {"worktree", "docs", "project"}


def _assert_write_allowed(conf: dict[str, Any], operation: str) -> None:
    if not _write_allowed(conf):
        raise PermissionError(f"repo_write_not_authorized:{operation}:{conf.get('write_scope', 'read_only')}")


def _policy_audit(action: str, payload: dict[str, Any]) -> None:
    try:
        from raphiia_openai import mongo_store

        doc = dict(payload)
        doc.update({"action": action, "created_at": _now_iso(), "capability": CAPABILITY})
        mongo_store.get_db()[REPO_POLICY_AUDIT_COLLECTION].insert_one(doc)
    except Exception:
        pass


def _validate_policy_payload(
    repo: str,
    repo_class: str,
    write_scope: str,
    allowed_paths: list[str] | None,
    allowed_commands_profile: str,
) -> dict[str, Any]:
    if not REPO_PATTERN.match(repo or ""):
        raise ValueError("repo_must_be_owner_name")
    owner, name = repo.split("/", 1)
    if owner not in OWNER_APPROVED_GITHUB_OWNERS and repo != GITLAB_COMMUNITY_RUNNER_REPO:
        raise PermissionError("repo_owner_not_approved")
    known_name = "gitlab-runner" if repo == GITLAB_COMMUNITY_RUNNER_REPO else name
    known = OWNER_APPROVED_REPO_CLASSES.get(known_name, {})
    scope = (write_scope or "read_only").strip()
    if scope not in {"read_only", "worktree", "docs", "project"}:
        raise ValueError("invalid_write_scope")
    profile = (allowed_commands_profile or known.get("profile") or "python-tests").strip()
    if profile not in ALLOWLISTED_COMMANDS:
        raise ValueError("invalid_allowed_commands_profile")
    paths = allowed_paths or list(known.get("allowed_paths") or OWNER_APPROVED_ALLOWED_PATHS)
    clean_paths = []
    for path in paths:
        rel = (path or "").replace("\\", "/").strip("/")
        if not rel or rel.startswith("../") or "/../" in rel:
            raise PermissionError("path_traversal_denied")
        parts = {part.lower() for part in rel.split("/") if part}
        if parts & DENIED_PATH_PARTS:
            raise PermissionError("secret_or_generated_path_denied")
        clean_paths.append(rel)
    return {
        "repo": repo,
        "owner": owner,
        "repo_class": repo_class or known.get("repo_class") or "owner-approved-readonly",
        "write_scope": scope,
        "allowed_paths": clean_paths,
        "allowed_commands": profile,
        "protected_branches": sorted(PROTECTED_BRANCHES),
        "package_roots": list(known.get("package_roots") or []),
        "requires_approval": scope != "read_only",
        "remote_url": f"https://github.com/{repo}.git",
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
    if rel.startswith("../") or "/../" in rel or rel == ".." or rel.startswith("/"):
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
            "repo_class": conf.get("repo_class"),
            "write_scope": conf.get("write_scope"),
            "requires_approval": conf.get("requires_approval"),
            "policy_status": conf.get("status"),
            "policy_source": conf.get("policy_source") or ("owner_approved_auto" if conf.get("owner_approved_auto") else "static"),
            "remote_url": conf.get("remote_url"),
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
        conf = _repo_config(repo)
        _assert_write_allowed(conf, "acquire_lock")
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
        _assert_write_allowed(conf, "create_worktree")
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
        _assert_write_allowed(conf, "apply_patch")
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
        _assert_write_allowed(conf, "write_file")
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
        _assert_write_allowed(conf, "run_command_allowlisted")
        profile = str(conf.get("profile") or "python-tests")
        if not (_command_allowed(command, profile) or (profile == "node-tests" and _node_package_command_allowed(command, conf))):
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
        _assert_write_allowed(conf, "commit_branch")
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


def repo_policy_status(repo: str | None = None) -> dict[str, Any]:
    """Return local execution repo policy without exposing secrets."""
    try:
        profiles = _load_repo_profiles()
        if repo:
            conf = _repo_config(repo)
            source = Path(conf["source_path"]).expanduser().resolve()
            return {
                "ok": True,
                "capability": CAPABILITY,
                "repo": repo,
                "owner": conf.get("owner"),
                "repo_class": conf.get("repo_class"),
                "write_scope": conf.get("write_scope"),
                "write_allowed": _write_allowed(conf),
                "requires_approval": conf.get("requires_approval"),
                "status": conf.get("status"),
                "policy_source": conf.get("policy_source") or ("owner_approved_auto" if conf.get("owner_approved_auto") else "static"),
                "allowed_paths": conf.get("allowed_paths", []),
                "allowed_commands": conf.get("profile"),
                "package_roots": conf.get("package_roots", []),
                "protected_branches": conf.get("protected_branches", sorted(PROTECTED_BRANCHES)),
                "source_exists": source.exists(),
                "source_is_git": (source / ".git").exists(),
                "source_path": str(source),
                "remote_url": conf.get("remote_url"),
            }
        by_class: dict[str, int] = {}
        entries = []
        for name, conf in sorted(profiles.items()):
            item = repo_policy_status(name)
            if item.get("ok"):
                by_class[str(item.get("repo_class") or "unknown")] = by_class.get(str(item.get("repo_class") or "unknown"), 0) + 1
                entries.append({k: item.get(k) for k in ("repo", "repo_class", "write_scope", "status", "policy_source", "source_exists")})
        return {
            "ok": True,
            "capability": CAPABILITY,
            "approved_owners": sorted(OWNER_APPROVED_GITHUB_OWNERS),
            "registry_collection": REPO_POLICY_COLLECTION,
            "count": len(entries),
            "by_class": by_class,
            "repos": entries,
        }
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "repo": repo, "error": str(exc)}


def repo_authorize(
    repo: str,
    repo_class: str = "product-app",
    write_scope: str = "worktree",
    allowed_paths: list[str] | None = None,
    allowed_commands_profile: str = "",
    approval_id: str = "",
    actor: str = "chatgpt",
    task_id: str = "",
    correlation_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Register or update an approved-owner repo policy."""
    try:
        _require_metadata(actor, task_id, correlation_id)
        if not (approval_id or "").strip():
            raise ValueError("approval_id_required")
        policy = _validate_policy_payload(repo, repo_class, write_scope, allowed_paths, allowed_commands_profile)
        now = _now_iso()
        policy.update(
            {
                "status": "active",
                "approval_id": approval_id,
                "authorized_by": actor,
                "updated_at": now,
                "last_verified": now,
            }
        )
        _policy_audit("authorize_dry_run" if dry_run else "authorize", {**policy, "task_id": task_id, "correlation_id": correlation_id})
        if not dry_run:
            from raphiia_openai import mongo_store

            mongo_store.get_db()[REPO_POLICY_COLLECTION].update_one(
                {"repo": repo},
                {"$set": policy, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        return {"ok": True, "capability": CAPABILITY, "dry_run": dry_run, "policy": policy}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "repo": repo, "error": str(exc)}


def repo_revoke(
    repo: str,
    approval_id: str,
    actor: str = "chatgpt",
    task_id: str = "",
    correlation_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Disable a repo policy; owner-approved repos still fall back to read-only onboarding."""
    try:
        _require_metadata(actor, task_id, correlation_id)
        if not (approval_id or "").strip():
            raise ValueError("approval_id_required")
        if not REPO_PATTERN.match(repo or ""):
            raise ValueError("repo_must_be_owner_name")
        payload = {"repo": repo, "approval_id": approval_id, "actor": actor, "task_id": task_id, "correlation_id": correlation_id}
        _policy_audit("revoke_dry_run" if dry_run else "revoke", payload)
        modified = 0
        if not dry_run:
            from raphiia_openai import mongo_store

            result = mongo_store.get_db()[REPO_POLICY_COLLECTION].update_one(
                {"repo": repo},
                {"$set": {"status": "revoked", "revoked_at": _now_iso(), "revoked_by": actor, "revoke_approval_id": approval_id}},
            )
            modified = int(getattr(result, "modified_count", 0) or 0)
        return {"ok": True, "capability": CAPABILITY, "dry_run": dry_run, "repo": repo, "modified_count": modified}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "repo": repo, "error": str(exc)}


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
        clone_url = (remote_url or conf.get("remote_url") or "").strip()
        if not clone_url:
            return {"ok": False, "error": "source_repo_missing_and_no_remote_url", "source_path": str(source)}
        clone = _run(["git", "clone", "--branch", base_ref, clone_url, str(source)], source.parent, timeout_seconds=600)
        return {"ok": clone["ok"], "repo": repo, "source_path": str(source), "clone": clone}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


local_exec_prepare_repo = prepare_repo
local_exec_hydrate_repo = prepare_repo
