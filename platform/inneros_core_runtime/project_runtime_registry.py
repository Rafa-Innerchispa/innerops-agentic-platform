"""Project Runtime Registry for safe local/peer project onboarding.

The registry is intentionally file-backed and boring: it maps a project_id/repo
to node-specific trusted runtime paths. It is not a secret store and it never
authorizes paths outside the InnerOS/project roots.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai.notifications import whatsapp_service_ops

CAPABILITY = "project_runtime_registry"
REGISTRY_VERSION = "1.0.0"
DEFAULT_INNEROS_CORE_ROOT = Path("/home/rlopez/inneros/inneros_core")
NODE_HELPER = "/home/rlopez/bin/ralfia-peer-node-helper"
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NESTED_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SAFE_REMOTE_RE = re.compile(r"^(https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\\.git)?|git@github\\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\\.git|https://gitlab.com/gitlab-community/gitlab-org/gitlab-runner(?:\\.git)?)$")
OWNER_APPROVED_GITHUB_OWNERS = {"Rafa-Innerchispa", "rafagye"}
OWNER_APPROVED_NESTED_REPOS = {"gitlab-community/gitlab-org/gitlab-runner"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _core_root() -> Path:
    return Path(os.getenv("INNEROS_CORE_ROOT", str(DEFAULT_INNEROS_CORE_ROOT))).expanduser().resolve()


def _registry_dir() -> Path:
    return _core_root() / "var" / "project_runtime_registry"


def _registry_file() -> Path:
    return _registry_dir() / "registry.json"


def trusted_roots(node: str = "primary") -> list[str]:
    # Paths are intentionally identical across .4/.5 so the ecosystem can fail over.
    core = _core_root()
    return [
        str(core / "workspaces"),
        "/home/rlopez/projects",
        str(core / "var" / "local_execution" / "repos"),
        str(core / "var" / "local_execution" / "worktrees"),
    ]


def _load() -> dict[str, Any]:
    path = _registry_file()
    if not path.exists():
        return {"version": REGISTRY_VERSION, "projects": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": REGISTRY_VERSION, "projects": {}}
    if not isinstance(data, dict):
        return {"version": REGISTRY_VERSION, "projects": {}}
    data.setdefault("version", REGISTRY_VERSION)
    data.setdefault("projects", {})
    return data


def _save(data: dict[str, Any]) -> None:
    path = _registry_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _project_id(value: str) -> str:
    item = (value or "").strip()
    if item in OWNER_APPROVED_NESTED_REPOS:
        item = item.rsplit("/", 1)[1]
    elif "/" in item and REPO_RE.match(item):
        item = item.split("/", 1)[1]
    if not PROJECT_ID_RE.match(item):
        raise ValueError("invalid_project_id")
    return item


def _repo(value: str | None, project_id: str) -> str:
    item = (value or "").strip() or f"Rafa-Innerchispa/{project_id}"
    if not (REPO_RE.match(item) or item in OWNER_APPROVED_NESTED_REPOS):
        raise ValueError("invalid_repo")
    owner = item.split("/", 1)[0]
    if owner not in OWNER_APPROVED_GITHUB_OWNERS and item not in OWNER_APPROVED_NESTED_REPOS:
        raise PermissionError("repo_owner_not_allowlisted")
    return item


def _safe_path(path: str, node: str = "primary") -> Path:
    raw = Path(path or "").expanduser()
    if not raw.is_absolute():
        raise PermissionError("absolute_project_path_required")
    resolved = raw.resolve()
    roots = [Path(p).expanduser().resolve() for p in trusted_roots(node)]
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise PermissionError("project_path_not_under_trusted_root")
    if resolved.is_symlink():
        raise PermissionError("project_path_symlink_denied")
    return resolved


def _default_path(project_id: str) -> str:
    return str(_core_root() / "workspaces" / project_id)


def register_project(
    project_id: str,
    repo: str | None = None,
    project_path: str = "",
    actor: str = "chatgpt",
    source: str = "manual",
    policy_class: str | None = None,
    write_scope: str | None = None,
    allowed_paths: list[str] | None = None,
    allowed_commands_profile: str | None = None,
    package_roots: list[str] | None = None,
) -> dict[str, Any]:
    pid = _project_id(project_id)
    full_repo = _repo(repo, pid)
    path = str(_safe_path(project_path or _default_path(pid)))
    data = _load()
    projects = data.setdefault("projects", {})
    existing = dict(projects.get(pid) or {})
    paths = dict(existing.get("paths") or {})
    paths.setdefault("primary", path)
    paths.setdefault("amd", path)
    entry = {
        **existing,
        "project_id": pid,
        "repo": full_repo,
        "paths": paths,
        "trusted_roots": {"primary": trusted_roots("primary"), "amd": trusted_roots("amd")},
        "policy_class": policy_class or existing.get("policy_class") or "product-app",
        "write_scope": write_scope or existing.get("write_scope") or "worktree",
        "updated_at": _now(),
        "updated_by": actor,
        "source": source,
    }
    if allowed_paths is not None:
        entry["allowed_paths"] = allowed_paths
    if allowed_commands_profile:
        entry["allowed_commands_profile"] = allowed_commands_profile
    if package_roots is not None:
        entry["package_roots"] = package_roots
    entry.setdefault("created_at", _now())
    projects[pid] = entry
    data["version"] = REGISTRY_VERSION
    _save(data)
    return {"ok": True, "capability": CAPABILITY, "project": entry}


def _find(project_id: str = "", repo: str = "") -> dict[str, Any] | None:
    data = _load()
    projects = data.get("projects") or {}
    if project_id:
        pid = _project_id(project_id)
        if pid in projects:
            return dict(projects[pid])
    if repo:
        full = _repo(repo, repo.split("/", 1)[1] if "/" in repo else repo)
        for entry in projects.values():
            if entry.get("repo") == full:
                return dict(entry)
    return None


def resolve_project(project_id: str = "", repo: str = "", node: str = "primary") -> dict[str, Any]:
    normalized_node = whatsapp_service_ops.normalize_node(node)
    entry = _find(project_id, repo)
    if not entry:
        pid = _project_id(project_id or repo)
        full_repo = _repo(repo, pid) if repo else ""
        return {
            "ok": False,
            "capability": CAPABILITY,
            "node": normalized_node,
            "error": "project_not_registered",
            "project_id": pid,
            "repo": full_repo,
        }
    paths = dict(entry.get("paths") or {})
    path = paths.get(normalized_node) or paths.get("primary") or _default_path(entry["project_id"])
    resolved = str(_safe_path(path, normalized_node))
    return {"ok": True, "capability": CAPABILITY, "node": normalized_node, "project": entry, "project_path": resolved}


def status(project_id: str = "", repo: str = "", node: str = "primary") -> dict[str, Any]:
    resolved = resolve_project(project_id=project_id, repo=repo, node=node)
    if not resolved.get("ok"):
        return resolved
    path = Path(resolved["project_path"])
    return {
        **resolved,
        "exists": path.exists(),
        "is_git": (path / ".git").exists(),
        "trusted_roots": trusted_roots(resolved["node"]),
    }


def _run_node(node: str, args: list[str], *, input_text: str = "", timeout: int = 120) -> subprocess.CompletedProcess[str]:
    normalized = whatsapp_service_ops.normalize_node(node)
    if normalized == whatsapp_service_ops._local_node():
        command = args
    else:
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "IdentitiesOnly=yes",
            "-i",
            whatsapp_service_ops.SSH_IDENTITY_FILE,
            whatsapp_service_ops.SSH_TARGETS[normalized],
            *args,
        ]
    return subprocess.run(command, input=input_text, capture_output=True, text=True, timeout=timeout, check=False)


def bootstrap_runtime(
    node: str = "primary",
    project_id: str = "",
    repo: str = "",
    remote_url: str = "",
    actor: str = "chatgpt",
    task_id: str = "",
    correlation_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    resolved = resolve_project(project_id=project_id or repo, repo=repo, node=node)
    path = resolved["project_path"]
    remote = (remote_url or "").strip()
    if remote and not SAFE_REMOTE_RE.match(remote):
        return {"ok": False, "error": "remote_url_not_allowlisted"}
    payload = json.dumps({"project_path": path, "repo": resolved["project"]["repo"], "remote_url": remote, "dry_run": dry_run})
    proc = _run_node(resolved["node"], [NODE_HELPER, "project_bootstrap"], input_text=payload, timeout=300)
    try:
        result = json.loads(proc.stdout or "{}")
    except Exception:
        result = {"ok": False, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
    ok = bool(result.get("ok")) and proc.returncode == 0
    return {**resolved, "ok": ok, "dry_run": dry_run, "result": result, "helper_returncode": proc.returncode}


def reconcile(
    project_id: str = "",
    repo: str = "",
    node: str = "primary",
    action: str = "plan",
    approval_id: str = "",
    dry_run: bool = True,
    actor: str = "chatgpt",
) -> dict[str, Any]:
    """Inspect/plan/apply safe legacy nested repo reconciliation.

    Apply promotes ``<project>/<project>`` to ``<project>`` only when the child
    is a Git repo and the root is not. It never operates outside trusted roots.
    """
    op = (action or "plan").strip().lower()
    if op not in {"inspect", "plan", "apply"}:
        return {"ok": False, "error": "action_not_allowlisted", "allowed": ["inspect", "plan", "apply"]}
    if op == "apply" and not approval_id:
        return {"ok": False, "error": "approval_id_required"}
    resolved = resolve_project(project_id=project_id or repo, repo=repo, node=node)
    project = resolved["project"]
    payload = json.dumps(
        {
            "project_id": project["project_id"],
            "project_path": resolved["project_path"],
            "dry_run": dry_run or op != "apply",
            "apply": op == "apply" and not dry_run,
        }
    )
    proc = _run_node(resolved["node"], [NODE_HELPER, "project_reconcile"], input_text=payload, timeout=300)
    try:
        result = json.loads(proc.stdout or "{}")
    except Exception:
        result = {"ok": False, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
    ok = bool(result.get("ok")) and proc.returncode == 0
    if ok and op == "apply" and result.get("applied"):
        data = _load()
        entry = data.setdefault("projects", {}).get(project["project_id"], project)
        paths = dict(entry.get("paths") or {})
        paths[resolved["node"]] = resolved["project_path"]
        paths.setdefault("primary", resolved["project_path"])
        paths.setdefault("amd", resolved["project_path"])
        entry["paths"] = paths
        entry["updated_at"] = _now()
        entry["updated_by"] = actor
        entry["last_reconcile"] = {"node": resolved["node"], "approval_id": approval_id, "result": result}
        data["projects"][project["project_id"]] = entry
        _save(data)
    return {**resolved, "ok": ok, "action": op, "dry_run": dry_run, "result": result, "helper_returncode": proc.returncode}


def migrate_existing(actor: str = "codex") -> dict[str, Any]:
    targets = [
        ("cozmo-alive", "Rafa-Innerchispa/cozmo-alive"),
        ("ralphiia-ecosystem-core", "Rafa-Innerchispa/ralphiia-ecosystem-core"),
        ("ralphiia-founderos-openai", "Rafa-Innerchispa/ralphiia-founderos-openai"),
        ("innerspark-workforce-ai", "Rafa-Innerchispa/innerspark-workforce-ai"),
        ("innerops-agentic-platform", "Rafa-Innerchispa/innerops-agentic-platform"),
    ]
    items = []
    for pid, repo in targets:
        path = _default_path(pid)
        items.append(register_project(pid, repo, path, actor=actor, source="migration"))
    return {"ok": all(i.get("ok") for i in items), "capability": CAPABILITY, "count": len(items), "items": items}
