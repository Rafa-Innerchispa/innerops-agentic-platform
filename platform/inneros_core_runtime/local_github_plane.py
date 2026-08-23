"""GitHub and project bootstrap plane for Ralphi IA owner operations."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from raphiia_openai import local_filesystem_plane

CAPABILITY = "local_github_plane"
MAX_OUTPUT = 12000
REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
DEFAULT_OWNERS = ["Rafa-Innerchispa"]


def _allowed_owners() -> set[str]:
    raw = os.getenv("RALFIA_GITHUB_OWNERS_JSON", "").strip()
    owners = DEFAULT_OWNERS
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                owners = parsed
        except json.JSONDecodeError:
            pass
    return set(owners)


def _bounded(text: str) -> str:
    value = text or ""
    if len(value.encode("utf-8", errors="replace")) <= MAX_OUTPUT:
        return value
    return value.encode("utf-8", errors="replace")[:MAX_OUTPUT].decode("utf-8", errors="replace") + "\n[TRUNCATED]"


def _run(argv: list[str], cwd: str | Path | None = None, timeout: int = 120) -> dict[str, Any]:
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": _bounded(proc.stdout),
        "stderr": _bounded(_redact(proc.stderr)),
        "argv": [argv[0], *argv[1:]],
    }


def _redact(text: str) -> str:
    return re.sub(r"(gh[opsu]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)", "[REDACTED]", text or "")


def _validate_owner_repo(owner: str, name: str) -> tuple[str, str]:
    owner = (owner or "").strip()
    name = (name or "").strip()
    if not OWNER_RE.match(owner):
        raise ValueError("invalid_github_owner")
    if owner not in _allowed_owners():
        raise PermissionError("github_owner_not_allowlisted")
    if not REPO_NAME_RE.match(name):
        raise ValueError("invalid_repo_name")
    return owner, name


def github_status() -> dict[str, Any]:
    gh_path = shutil_which("gh")
    token_present = bool(os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"))
    status = {
        "ok": True,
        "capability": CAPABILITY,
        "gh_available": bool(gh_path),
        "gh_path": gh_path,
        "env_token_present": token_present,
        "allowed_owners": sorted(_allowed_owners()),
    }
    if gh_path:
        auth = _run([gh_path, "auth", "status"], timeout=30)
        status["gh_auth_ok"] = bool(auth["ok"])
        status["gh_auth_status"] = _redact((auth.get("stdout") or "") + (auth.get("stderr") or ""))
    else:
        status["gh_auth_ok"] = False
    return status


def shutil_which(name: str) -> str | None:
    search_dirs = [p for p in os.getenv("PATH", "").split(os.pathsep) if p]
    search_dirs.extend([str(Path.home() / ".local" / "bin"), "/snap/bin", "/usr/local/bin", "/usr/bin"])
    for directory in dict.fromkeys(search_dirs):
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def create_github_repo(
    owner: str,
    name: str,
    description: str = "",
    private: bool = True,
    homepage: str | None = None,
    actor: str = "chatgpt",
    task_id: str = "manual",
    correlation_id: str = "manual",
) -> dict[str, Any]:
    try:
        local_filesystem_plane._require_metadata(actor, task_id, correlation_id)
        owner, name = _validate_owner_repo(owner, name)
        full = f"{owner}/{name}"
        gh_path = shutil_which("gh")
        if gh_path:
            view = _run([gh_path, "repo", "view", full, "--json", "nameWithOwner,url,isPrivate"], timeout=60)
            if view["ok"]:
                try:
                    data = json.loads(view["stdout"])
                except json.JSONDecodeError:
                    data = {}
                return {"ok": True, "idempotent": True, "repo": full, "url": data.get("url"), "private": data.get("isPrivate"), "backend": "gh"}
            args = [gh_path, "repo", "create", full, "--disable-wiki", "--disable-issues"]
            args.append("--private" if private else "--public")
            if description:
                args += ["--description", description[:350]]
            if homepage:
                args += ["--homepage", homepage]
            created = _run(args, timeout=120)
            if not created["ok"]:
                return {"ok": False, "repo": full, "backend": "gh", "error": "github_create_failed", "detail": created}
            url = f"https://github.com/{full}"
            local_filesystem_plane._audit("github_create_repo", actor, Path(f"/home/rlopez/{name}"), {"ok": True, "repo": full, "url": url}, {"task_id": task_id, "correlation_id": correlation_id})
            return {"ok": True, "repo": full, "url": url, "private": private, "backend": "gh", "created": created}
        return _create_github_repo_api(owner, name, description, private, homepage, actor, task_id, correlation_id)
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def _create_github_repo_api(
    owner: str,
    name: str,
    description: str,
    private: bool,
    homepage: str | None,
    actor: str,
    task_id: str,
    correlation_id: str,
) -> dict[str, Any]:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        return {"ok": False, "error": "github_credentials_unavailable", "hint": "install gh or set server-side GITHUB_TOKEN/GH_TOKEN"}
    base = f"https://api.github.com/repos/{owner}/{name}"
    req = urllib.request.Request(base, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "idempotent": True, "repo": data.get("full_name"), "url": data.get("html_url"), "private": data.get("private"), "backend": "api"}
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return {"ok": False, "error": "github_view_failed", "status": exc.code}
    payload = json.dumps({"name": name, "description": description[:350], "private": private, "homepage": homepage or ""}).encode("utf-8")
    endpoint = f"https://api.github.com/orgs/{owner}/repos"
    req = urllib.request.Request(endpoint, data=payload, method="POST", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            local_filesystem_plane._audit("github_create_repo", actor, Path(f"/home/rlopez/{name}"), {"ok": True, "repo": data.get("full_name"), "url": data.get("html_url")}, {"task_id": task_id, "correlation_id": correlation_id})
            return {"ok": True, "repo": data.get("full_name"), "url": data.get("html_url"), "private": data.get("private"), "backend": "api"}
    except urllib.error.HTTPError as exc:
        detail = _redact(exc.read().decode("utf-8", errors="replace")[:2000])
        return {"ok": False, "error": "github_create_failed", "status": exc.code, "detail": detail}


def bootstrap_project(
    path: str,
    project_name: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    description: str = "",
    github_owner: str = "Rafa-Innerchispa",
    create_remote: bool = False,
    private: bool = True,
) -> dict[str, Any]:
    try:
        local_filesystem_plane._require_metadata(actor, task_id, correlation_id)
        if not REPO_NAME_RE.match(project_name or ""):
            raise ValueError("invalid_project_name")
        root = Path(local_filesystem_plane._safe_resolve(path))
        project_dir = root if root.name == project_name else root / project_name
        local_filesystem_plane.mkdir(str(project_dir), actor, task_id, correlation_id)
        readme = project_dir / "README.md"
        if not readme.exists():
            title = project_name.replace("-", " ").replace("_", " ").title()
            local_filesystem_plane.write_file(
                str(readme),
                f"# {title}\n\n{description or 'InnerOS project scaffold.'}\n",
                actor,
                task_id,
                correlation_id,
                mode="create",
            )
        git = local_filesystem_plane.git_init_repo(str(project_dir), actor, task_id, correlation_id)
        result: dict[str, Any] = {"ok": True, "path": str(project_dir), "git": git, "remote": None}
        if create_remote:
            remote = create_github_repo(github_owner, project_name, description, private, actor=actor, task_id=task_id, correlation_id=correlation_id)
            result["remote"] = remote
            if remote.get("ok") and remote.get("url"):
                remotes = _run(["git", "remote"], cwd=project_dir, timeout=20)
                if "origin" not in (remotes.get("stdout") or "").split():
                    result["git_remote_add"] = _run(["git", "remote", "add", "origin", str(remote["url"]) + ".git"], cwd=project_dir, timeout=30)
        try:
            from raphiia_openai import project_runtime_registry as prr

            full_repo = f"{github_owner}/{project_name}"
            result["runtime_registry"] = prr.register_project(
                project_id=project_name,
                repo=full_repo,
                project_path=str(project_dir),
                actor=actor,
                source="local_project_bootstrap",
            )
        except Exception as exc:
            result["ok"] = False
            result["partial"] = True
            result["runtime_registry"] = {"ok": False, "error": str(exc)}
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}
