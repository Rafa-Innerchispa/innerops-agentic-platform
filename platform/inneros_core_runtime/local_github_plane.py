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
TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
DEFAULT_OWNERS = ["Rafa-Innerchispa"]
PROFILE_FIELDS = {"name", "bio", "company", "blog", "location", "hireable", "twitter_username"}
DEFAULT_GITHUB_LIMIT = 100
MAX_TOPICS = 20


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


def _bounded(text: str, max_output: int = MAX_OUTPUT) -> str:
    value = text or ""
    if max_output <= 0 or len(value.encode("utf-8", errors="replace")) <= max_output:
        return value
    return value.encode("utf-8", errors="replace")[:max_output].decode("utf-8", errors="replace") + "\n[TRUNCATED]"


def _run(argv: list[str], cwd: str | Path | None = None, timeout: int = 120, input_text: str | None = None, max_output: int = MAX_OUTPUT) -> dict[str, Any]:
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": _bounded(proc.stdout, max_output),
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
            result["partial"] = True
            result["runtime_registry"] = {"ok": False, "error": str(exc)}
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}



def _gh_path() -> str | None:
    return shutil_which("gh")


def _json_result(result: dict[str, Any]) -> Any:
    try:
        return json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError:
        return {}


def _current_scopes(gh_path: str | None = None) -> list[str]:
    gh = gh_path or _gh_path()
    if not gh:
        return []
    auth = _run([gh, "auth", "status", "--hostname", "github.com"], timeout=30)
    text = f"{auth.get('stdout') or ''}\n{auth.get('stderr') or ''}"
    match = re.search(r"Token scopes:\s*(.+)", text)
    if not match:
        return []
    return sorted(set(re.findall(r"'([^']+)'", match.group(1))))


def _repo_requires_freeze_review(name: str) -> bool:
    lowered = (name or "").lower()
    markers = ("hackathon", "challenge", "xprize", "alpaca", "uipath", "chutes", "vigil", "hyperloom", "mi325x")
    return any(marker in lowered for marker in markers)


def _normalize_topics(topics: list[str] | None) -> list[str] | None:
    if topics is None:
        return None
    normalized = []
    for topic in topics:
        value = str(topic or "").strip().lower()
        if not value:
            continue
        if not TOPIC_RE.match(value):
            raise ValueError(f"invalid_github_topic:{value}")
        if value not in normalized:
            normalized.append(value)
    if len(normalized) > MAX_TOPICS:
        raise ValueError("too_many_github_topics")
    return normalized


def _repo_view(gh_path: str, full: str) -> tuple[dict[str, Any], dict[str, Any]]:
    view = _run(
        [
            gh_path,
            "api",
            f"repos/{full}",
            "--jq",
            "{name:.name,full_name:.full_name,html_url:.html_url,description:.description,homepage:.homepage,archived:.archived,disabled:.disabled,visibility:.visibility,permissions:.permissions,default_branch:.default_branch,node_id:.node_id}",
        ],
        timeout=60,
    )
    return view, _json_result(view)


def _can_mutate_repo(meta: dict[str, Any]) -> bool:
    perms = meta.get("permissions") or {}
    return bool((perms.get("admin") or perms.get("maintain") or perms.get("push")) and not meta.get("archived") and not meta.get("disabled"))


def _audit_github(action: str, actor: str, task_id: str, correlation_id: str, result: dict[str, Any], repo_name: str = "github") -> None:
    try:
        local_filesystem_plane._audit(action, actor, Path(f"/home/rlopez/{repo_name}"), result, {"task_id": task_id, "correlation_id": correlation_id})
    except Exception:
        pass


def audit_github_professionalization(owner: str = "Rafa-Innerchispa", limit: int = DEFAULT_GITHUB_LIMIT, include_rows: bool = False) -> dict[str, Any]:
    """Read-only GitHub capability matrix for repo/profile professionalization."""
    try:
        owner = (owner or "").strip()
        if not OWNER_RE.match(owner):
            raise ValueError("invalid_github_owner")
        if owner not in _allowed_owners():
            raise PermissionError("github_owner_not_allowlisted")
        gh = _gh_path()
        if not gh:
            return {"ok": False, "capability": CAPABILITY, "error": "gh_unavailable"}
        limit = max(1, min(int(limit or DEFAULT_GITHUB_LIMIT), 100))
        fields = "name,nameWithOwner,isPrivate,isArchived,description,homepageUrl,repositoryTopics,url,defaultBranchRef,pushedAt,updatedAt"
        listed = _run([gh, "repo", "list", owner, "--limit", str(limit), "--json", fields], timeout=120, max_output=MAX_OUTPUT * 20)
        if not listed["ok"]:
            return {"ok": False, "capability": CAPABILITY, "error": "github_repo_list_failed", "detail": listed}
        repos = _json_result(listed)
        if not isinstance(repos, list):
            return {"ok": False, "capability": CAPABILITY, "error": "github_repo_list_invalid_json", "detail": {"stdout_len": len(listed.get("stdout") or ""), "truncated": "[TRUNCATED]" in (listed.get("stdout") or "")}}
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for repo in repos:
            full = repo.get("nameWithOwner") or f"{owner}/{repo.get('name', '')}"
            view, meta = _repo_view(gh, full)
            if not view["ok"]:
                errors.append({"repo": full, "error": "repo_view_failed", "detail": view})
                meta = {}
            topics = repo.get("repositoryTopics") or []
            if isinstance(topics, dict):
                topics = topics.get("nodes") or []
            topic_names = [((item.get("topic") or {}).get("name") if isinstance(item, dict) else str(item)) for item in topics]
            topic_names = [name for name in topic_names if name]
            freeze_review = _repo_requires_freeze_review(repo.get("name") or meta.get("name") or full)
            can_mutate = _can_mutate_repo(meta)
            rows.append(
                {
                    "repo": full,
                    "private": bool(repo.get("isPrivate")),
                    "archived": bool(repo.get("isArchived") or meta.get("archived")),
                    "default_branch": ((repo.get("defaultBranchRef") or {}).get("name") if isinstance(repo.get("defaultBranchRef"), dict) else None) or meta.get("default_branch"),
                    "description_present": bool(repo.get("description")),
                    "homepage_present": bool(repo.get("homepageUrl")),
                    "topics_count": len(topic_names),
                    "permissions": meta.get("permissions") or {},
                    "dryrun_can_update_repo_metadata": can_mutate,
                    "dryrun_can_update_topics": can_mutate,
                    "requires_freeze_review_before_mutation": freeze_review,
                    "safe_now_action": "READ_ONLY_FREEZE_REVIEW" if freeze_review else ("METADATA_DRYRUN_ELIGIBLE" if can_mutate else "BLOCKED_BY_PERMISSION_OR_STATE"),
                    "url": repo.get("url") or meta.get("html_url"),
                }
            )
        scopes = _current_scopes(gh)
        profile = _run([gh, "api", "user", "--jq", "{login:.login,id:.id,type:.type,name:.name,bio:.bio,company:.company,blog:.blog,email:.email}"], timeout=60)
        pins = _run([gh, "api", "graphql", "-f", "query=query { viewer { login pinnedItems(first: 6, types: REPOSITORY) { totalCount nodes { ... on Repository { nameWithOwner url } } } } }"], timeout=60)
        result: dict[str, Any] = {
            "ok": True,
            "capability": CAPABILITY,
            "truth_boundary": "DRY_RUN_READ_ONLY_NO_MUTATIONS",
            "owner": owner,
            "repo_count": len(rows),
            "public_count": sum(1 for row in rows if not row["private"]),
            "private_count": sum(1 for row in rows if row["private"]),
            "archived_count": sum(1 for row in rows if row["archived"]),
            "metadata_dryrun_eligible_count": sum(1 for row in rows if row["dryrun_can_update_repo_metadata"] and not row["requires_freeze_review_before_mutation"]),
            "topics_dryrun_eligible_count": sum(1 for row in rows if row["dryrun_can_update_topics"] and not row["requires_freeze_review_before_mutation"]),
            "freeze_review_required_count": sum(1 for row in rows if row["requires_freeze_review_before_mutation"]),
            "missing_description_count": sum(1 for row in rows if not row["description_present"]),
            "missing_homepage_count": sum(1 for row in rows if not row["homepage_present"]),
            "topicless_count": sum(1 for row in rows if row["topics_count"] == 0),
            "current_gh_scopes": scopes,
            "repo_metadata_topics_scope_result": "CURRENT_SCOPES_SUFFICIENT_FOR_OWNED_REPOS_WITH_PUSH_OR_ADMIN_PERMISSION_DRYRUN_ELIGIBLE",
            "bio_pins_minimum_missing_oauth_scope_classic_pat": None if "user" in scopes else "user",
            "profile_read_ok": bool(profile["ok"]),
            "pinned_read_ok": bool(pins["ok"]),
            "errors": errors,
        }
        if include_rows:
            result["rows"] = rows
        else:
            result["sample"] = rows[:10]
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def update_repo_professionalization(
    owner: str,
    name: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    description: str | None = None,
    homepage: str | None = None,
    topics: list[str] | None = None,
    dry_run: bool = True,
    freeze_override: bool = False,
) -> dict[str, Any]:
    """Plan or apply reversible repo metadata/topic updates through official GitHub APIs."""
    try:
        local_filesystem_plane._require_metadata(actor, task_id, correlation_id)
        owner, name = _validate_owner_repo(owner, name)
        gh = _gh_path()
        if not gh:
            return {"ok": False, "capability": CAPABILITY, "error": "gh_unavailable"}
        full = f"{owner}/{name}"
        topics_norm = _normalize_topics(topics)
        if homepage is not None and homepage and not re.match(r"^https?://[^\s]+$", homepage):
            raise ValueError("invalid_homepage_url")
        view, current = _repo_view(gh, full)
        if not view["ok"]:
            return {"ok": False, "capability": CAPABILITY, "error": "github_repo_view_failed", "detail": view}
        freeze_review = _repo_requires_freeze_review(name)
        can_mutate = _can_mutate_repo(current)
        plan = {"description": description[:350] if description is not None else None, "homepage": homepage if homepage is not None else None, "topics": topics_norm}
        result: dict[str, Any] = {
            "ok": bool(dry_run or (can_mutate and (not freeze_review or freeze_override))),
            "capability": CAPABILITY,
            "repo": full,
            "dry_run": dry_run,
            "truth_boundary": "DRY_RUN_NO_MUTATION" if dry_run else "APPLIED_OFFICIAL_GITHUB_API",
            "current": current,
            "plan": plan,
            "requires_freeze_review_before_mutation": freeze_review,
            "can_mutate_with_current_auth": can_mutate,
        }
        if freeze_review and not freeze_override:
            result["blocked_for_apply"] = "hackathon_or_submission_freeze_review_required"
        if not can_mutate:
            result["blocked_for_apply"] = "github_permission_or_repo_state_denied"
        if dry_run or result.get("blocked_for_apply"):
            return result
        metadata_payload = {key: value for key, value in {"description": plan["description"], "homepage": plan["homepage"]}.items() if value is not None}
        if metadata_payload:
            patch = _run([gh, "api", "-X", "PATCH", f"repos/{full}", "--input", "-"], input_text=json.dumps(metadata_payload), timeout=60)
            result["metadata_update"] = patch
            if not patch["ok"]:
                result["ok"] = False
                result["error"] = "metadata_update_failed"
                return result
        if topics_norm is not None:
            topic_update = _run([gh, "api", "-X", "PUT", f"repos/{full}/topics", "--input", "-"], input_text=json.dumps({"names": topics_norm}), timeout=60)
            result["topics_update"] = topic_update
            if not topic_update["ok"]:
                result["ok"] = False
                result["error"] = "topics_update_failed"
                return result
        _audit_github("github_update_repo_professionalization", actor, task_id, correlation_id, result, name)
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def update_owner_profile(actor: str, task_id: str, correlation_id: str, dry_run: bool = True, **fields: object) -> dict[str, Any]:
    """Plan or apply owner profile updates; apply requires a server-side token with user scope."""
    try:
        local_filesystem_plane._require_metadata(actor, task_id, correlation_id)
        gh = _gh_path()
        if not gh:
            return {"ok": False, "capability": CAPABILITY, "error": "gh_unavailable"}
        payload = {key: fields[key] for key in PROFILE_FIELDS if key in fields and fields[key] is not None}
        unknown = sorted(set(fields) - PROFILE_FIELDS)
        if unknown:
            raise ValueError(f"unsupported_profile_fields:{','.join(unknown)}")
        scopes = _current_scopes(gh)
        result: dict[str, Any] = {
            "ok": bool(dry_run or "user" in scopes),
            "capability": CAPABILITY,
            "dry_run": dry_run,
            "truth_boundary": "DRY_RUN_NO_MUTATION" if dry_run else "APPLIED_OFFICIAL_GITHUB_API",
            "current_gh_scopes": scopes,
            "required_scope": None if "user" in scopes else "user",
            "plan": payload,
        }
        if dry_run or "user" not in scopes:
            if "user" not in scopes:
                result["blocked_for_apply"] = "missing_github_user_scope"
            return result
        applied = _run([gh, "api", "-X", "PATCH", "user", "--input", "-"], input_text=json.dumps(payload), timeout=60)
        result["profile_update"] = applied
        result["ok"] = bool(applied["ok"])
        if not applied["ok"]:
            result["error"] = "profile_update_failed"
        _audit_github("github_update_owner_profile", actor, task_id, correlation_id, result)
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def pin_repositories(owner: str, repositories: list[str], actor: str, task_id: str, correlation_id: str, dry_run: bool = True) -> dict[str, Any]:
    """Plan or apply additive GitHub pinned repositories. It never unpins existing repos."""
    try:
        local_filesystem_plane._require_metadata(actor, task_id, correlation_id)
        owner = (owner or "").strip()
        if owner not in _allowed_owners():
            raise PermissionError("github_owner_not_allowlisted")
        gh = _gh_path()
        if not gh:
            return {"ok": False, "capability": CAPABILITY, "error": "gh_unavailable"}
        targets = []
        for repo in repositories or []:
            repo_owner, repo_name = (repo.split("/", 1) if "/" in repo else (owner, repo))
            repo_owner, repo_name = _validate_owner_repo(repo_owner, repo_name)
            targets.append(f"{repo_owner}/{repo_name}")
        if not targets or len(targets) > 6:
            raise ValueError("pinned_repositories_must_be_1_to_6")
        scopes = _current_scopes(gh)
        nodes = []
        for full in targets:
            view, meta = _repo_view(gh, full)
            nodes.append({"repo": full, "view_ok": view["ok"], "node_id": meta.get("node_id")})
        result: dict[str, Any] = {
            "ok": bool(dry_run or "user" in scopes),
            "capability": CAPABILITY,
            "dry_run": dry_run,
            "truth_boundary": "DRY_RUN_NO_MUTATION" if dry_run else "APPLIED_OFFICIAL_GITHUB_GRAPHQL",
            "current_gh_scopes": scopes,
            "required_scope": None if "user" in scopes else "user",
            "plan": {"pin_repositories_additive_only": targets},
            "nodes": nodes,
        }
        if dry_run or "user" not in scopes:
            if "user" not in scopes:
                result["blocked_for_apply"] = "missing_github_user_scope"
            return result
        mutation = "mutation($id:ID!){ pinRepository(input:{repositoryId:$id}) { clientMutationId } }"
        applied = []
        for node in nodes:
            if not node.get("node_id"):
                applied.append({"repo": node["repo"], "ok": False, "error": "missing_node_id"})
                continue
            run = _run([gh, "api", "graphql", "-f", f"query={mutation}", "-f", f"id={node['node_id']}"], timeout=60)
            applied.append({"repo": node["repo"], "ok": run["ok"], "result": run})
        result["applied"] = applied
        result["ok"] = all(item["ok"] for item in applied)
        if not result["ok"]:
            result["error"] = "pin_repository_failed"
        _audit_github("github_pin_repositories", actor, task_id, correlation_id, result)
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}
