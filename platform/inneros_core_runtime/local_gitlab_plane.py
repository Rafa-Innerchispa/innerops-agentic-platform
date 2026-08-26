"""GitLab provider plane for InnerOS Resource Fabric.

The plane is intentionally local-first aware: GitLab is treated as a specialized
external development resource for repos, CI/CD, merge requests, and traceability,
not as a default model/runtime engine.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import funding_registry, mongo_store, owner_vault

CAPABILITY = "local_gitlab_plane"
PROVIDER_ID = "gitlab-com"
MODEL_PROVIDER_ID = "gitlab-duo-optional"
VAULT_CATEGORY = "gitlab"
VAULT_KEY = "personal_access_token"
API_BASE = os.getenv("GITLAB_API_BASE", "https://gitlab.com/api/v4").rstrip("/")
MAX_OUTPUT = 12000
MAX_LIMIT = 100
DEFAULT_NAMESPACES = ["rafagye"]
CREDIT_ACCOUNT_NAME = "GitLab Contributor Reward Credits @rafagye"
CREDIT_ACCOUNT_REF = "gitlab_rafagye_contributor_rewards"
COL_AUDIT = "ralfia_gitlab_audit"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded(value: str) -> str:
    text = value or ""
    if len(text.encode("utf-8", errors="replace")) <= MAX_OUTPUT:
        return text
    return text.encode("utf-8", errors="replace")[:MAX_OUTPUT].decode("utf-8", errors="replace") + "\n[TRUNCATED]"


def _redact(value: str) -> str:
    text = value or ""
    text = re.sub(r"(glpat-[A-Za-z0-9_\-]{10,}|[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})", "[REDACTED]", text)
    text = re.sub(r"(PRIVATE-TOKEN|JOB-TOKEN|Authorization)(:\s*|=\s*)(Bearer\s+)?[^\s,;]+", r"\1\2[REDACTED]", text, flags=re.IGNORECASE)
    return text


def _limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, MAX_LIMIT))


def _namespaces() -> list[str]:
    raw = os.getenv("RALFIA_GITLAB_NAMESPACES_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
                return sorted({item.strip() for item in parsed if item.strip()})
        except json.JSONDecodeError:
            pass
    return DEFAULT_NAMESPACES[:]


def _token() -> tuple[str, str]:
    cred = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=True)
    secret = str(cred.get("secret") or "").strip() if cred.get("ok") else ""
    if secret:
        return secret, "owner_vault:gitlab/personal_access_token"
    env_secret = (os.getenv("GITLAB_TOKEN") or os.getenv("GITLAB_ACCESS_TOKEN") or os.getenv("GLAB_TOKEN") or "").strip()
    if env_secret:
        return env_secret, "env:GITLAB_TOKEN"
    return "", "missing"


def _which(name: str) -> str | None:
    search_dirs = [item for item in os.getenv("PATH", "").split(os.pathsep) if item]
    search_dirs.extend([str(Path.home() / ".local" / "bin"), "/snap/bin", "/usr/local/bin", "/usr/bin"])
    for directory in dict.fromkeys(search_dirs):
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _run(argv: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return {"ok": False, "error": "command_not_found", "argv": [argv[0], *argv[1:]]}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "error": "timeout", "stdout": _bounded(exc.stdout or ""), "stderr": _redact(_bounded(exc.stderr or "")), "argv": [argv[0], *argv[1:]]}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": _bounded(proc.stdout),
        "stderr": _redact(_bounded(proc.stderr)),
        "argv": [argv[0], *argv[1:]],
    }


def project_api_path(project_id_or_path: str) -> str:
    value = (project_id_or_path or "").strip()
    if not value:
        raise ValueError("project_id_or_path_required")
    return urllib.parse.quote(value, safe="") if "/" in value else urllib.parse.quote(value, safe="")


def _request(method: str, path: str, payload: dict[str, Any] | None = None, query: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    token, source = _token()
    if not token:
        return {"ok": False, "error": "gitlab_token_missing", "token_source": source, "hint": "store token with local_gitlab_store_pat_server_side"}
    url = f"{API_BASE}{path}"
    if query:
        cleaned = {key: value for key, value in query.items() if value not in (None, "")}
        if cleaned:
            url = f"{url}?{urllib.parse.urlencode(cleaned)}"
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method.upper(),
        headers={
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
            "User-Agent": "InnerOS-RalphiIA-GitLab-Plane/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else None
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "data": parsed, "token_source": source}
    except urllib.error.HTTPError as exc:
        detail = _redact(exc.read().decode("utf-8", errors="replace")[:2000])
        return {"ok": False, "status": exc.code, "error": "gitlab_http_error", "detail": detail, "token_source": source}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": "gitlab_unreachable", "detail": _redact(str(exc.reason)), "token_source": source}


def _audit(action: str, result: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
    doc = {
        "action": action,
        "result_ok": bool(result.get("ok")),
        "result": {key: value for key, value in result.items() if key not in {"data"}},
        "metadata": metadata or {},
        "created_at": _now(),
        "capability": CAPABILITY,
    }
    try:
        mongo_store.get_db()[COL_AUDIT].insert_one(doc)
    except Exception:
        pass


def store_pat_server_side(secret: str, label: str = "GitLab Personal Access Token", actor: str = "RAFAEL") -> dict[str, Any]:
    result = owner_vault.save_owner_credential(
        key=VAULT_KEY,
        secret=secret,
        category=VAULT_CATEGORY,
        label=label,
        actor=actor,
        metadata={"provider": PROVIDER_ID, "api_base": API_BASE, "stored_for": CAPABILITY},
    )
    return {**result, "secret_stored": bool(result.get("ok")), "secret_returned": False}


def glab_preflight() -> dict[str, Any]:
    path = _which("glab")
    token, source = _token()
    result: dict[str, Any] = {
        "ok": True,
        "capability": CAPABILITY,
        "glab_available": bool(path),
        "glab_path": path,
        "token_present": bool(token),
        "token_source": source,
        "install_required": not bool(path),
    }
    if path:
        result["version"] = _run([path, "--version"], timeout=20)
        env = os.environ.copy()
        if token:
            env["GITLAB_TOKEN"] = token
        result["auth_note"] = "glab can use GITLAB_TOKEN when present; REST API remains primary for MCP tools."
    return result


def gitlab_status() -> dict[str, Any]:
    token, source = _token()
    result: dict[str, Any] = {
        "ok": True,
        "capability": CAPABILITY,
        "provider_id": PROVIDER_ID,
        "api_base": API_BASE,
        "token_present": bool(token),
        "token_source": source,
        "allowed_namespaces": _namespaces(),
        "local_first_policy": "GitLab is external specialized resource; AMD .5 and Intel .4 remain default execution nodes.",
        "auth_ok": False,
        "verified_user": None,
        "duo_ai_gateway_status": "not_verified_without_account_or_license_probe",
    }
    if token:
        user = _request("GET", "/user", timeout=20)
        result["auth_ok"] = bool(user.get("ok"))
        result["auth_status"] = user.get("status")
        if user.get("ok") and isinstance(user.get("data"), dict):
            data = user["data"]
            result["verified_user"] = {
                "id": data.get("id"),
                "username": data.get("username"),
                "name": data.get("name"),
                "state": data.get("state"),
                "web_url": data.get("web_url"),
            }
        else:
            result["auth_error"] = {key: value for key, value in user.items() if key not in {"data"}}
    else:
        result["blocker"] = "gitlab_token_missing"
    result["glab"] = glab_preflight()
    return result


def list_projects(search: str = "", owned: bool = False, membership: bool = True, limit: int = 20) -> dict[str, Any]:
    query: dict[str, Any] = {"simple": "true", "per_page": _limit(limit), "membership": "true" if membership else "", "owned": "true" if owned else ""}
    if search:
        query["search"] = search.strip()
    res = _request("GET", "/projects", query=query)
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {
        "ok": True,
        "count": len(rows),
        "projects": [
            {
                "id": item.get("id"),
                "path_with_namespace": item.get("path_with_namespace"),
                "name": item.get("name"),
                "visibility": item.get("visibility"),
                "web_url": item.get("web_url"),
                "default_branch": item.get("default_branch"),
                "last_activity_at": item.get("last_activity_at"),
            }
            for item in rows
            if isinstance(item, dict)
        ],
    }


def list_groups(search: str = "", limit: int = 20) -> dict[str, Any]:
    query: dict[str, Any] = {"per_page": _limit(limit), "top_level_only": "false"}
    if search:
        query["search"] = search.strip()
    res = _request("GET", "/groups", query=query)
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {
        "ok": True,
        "count": len(rows),
        "groups": [
            {
                "id": item.get("id"),
                "full_path": item.get("full_path"),
                "name": item.get("name"),
                "visibility": item.get("visibility"),
                "web_url": item.get("web_url"),
            }
            for item in rows
            if isinstance(item, dict)
        ],
    }


def user_profile(username: str = "") -> dict[str, Any]:
    if not username:
        status = gitlab_status()
        return {"ok": bool(status.get("auth_ok")), "profile": status.get("verified_user"), "source": "authenticated_user", "auth_error": status.get("auth_error")}
    res = _request("GET", "/users", query={"username": username.strip(), "per_page": 1})
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    item = rows[0] if rows and isinstance(rows[0], dict) else {}
    return {
        "ok": bool(item),
        "profile": {
            "id": item.get("id"),
            "username": item.get("username"),
            "name": item.get("name"),
            "state": item.get("state"),
            "web_url": item.get("web_url"),
        } if item else None,
    }


def user_events(username: str = "rafagye", action: str = "", limit: int = 20) -> dict[str, Any]:
    path = f"/users/{urllib.parse.quote(username.strip(), safe='')}/events"
    query: dict[str, Any] = {"per_page": _limit(limit)}
    if action:
        query["action"] = action.strip()
    res = _request("GET", path, query=query)
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {
        "ok": True,
        "count": len(rows),
        "username": username,
        "events": [
            {
                "id": item.get("id"),
                "action_name": item.get("action_name"),
                "target_type": item.get("target_type"),
                "target_title": item.get("target_title"),
                "project_id": item.get("project_id"),
                "created_at": item.get("created_at"),
            }
            for item in rows
            if isinstance(item, dict)
        ],
    }


def discover_contribution_issues(search: str = "good first issue", labels: str = "", limit: int = 20) -> dict[str, Any]:
    capped_limit = _limit(limit)
    query: dict[str, Any] = {"scope": "all", "state": "opened", "per_page": capped_limit}
    if search:
        query["search"] = search.strip()
    if labels:
        query["labels"] = labels.strip()
    res = _request("GET", "/issues", query=query)
    fallback_error: dict[str, Any] | None = None
    if res.get("ok"):
        rows = res.get("data") if isinstance(res.get("data"), list) else []
        fallback_used = False
    else:
        fallback_error = {key: value for key, value in res.items() if key not in {"data"}}
        project_rows: list[dict[str, Any]] = []
        projects = list_projects(search=search, membership=True, limit=min(capped_limit, 10))
        if projects.get("ok"):
            for project in projects.get("projects", []):
                path = project.get("path_with_namespace") or project.get("id")
                if not path:
                    continue
                project_query: dict[str, Any] = {"state": "opened", "per_page": max(1, capped_limit - len(project_rows))}
                if search:
                    project_query["search"] = search.strip()
                if labels:
                    project_query["labels"] = labels.strip()
                issue_res = _request("GET", f"/projects/{project_api_path(str(path))}/issues", query=project_query)
                if issue_res.get("ok") and isinstance(issue_res.get("data"), list):
                    project_rows.extend([item for item in issue_res["data"] if isinstance(item, dict)])
                if len(project_rows) >= capped_limit:
                    break
        rows = project_rows[:capped_limit]
        fallback_used = True
    return {
        "ok": True,
        "fallback_used": fallback_used,
        "global_search_error": fallback_error,
        "count": len(rows),
        "issues": [
            _issue_summary(item)
            for item in rows
            if isinstance(item, dict)
        ],
    }


def project_summary(project_id_or_path: str) -> dict[str, Any]:
    encoded = project_api_path(project_id_or_path)
    res = _request("GET", f"/projects/{encoded}", query={"statistics": "false"})
    if not res.get("ok"):
        return res
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    return {
        "ok": True,
        "project": {
            "id": data.get("id"),
            "path_with_namespace": data.get("path_with_namespace"),
            "name": data.get("name"),
            "description": data.get("description"),
            "visibility": data.get("visibility"),
            "web_url": data.get("web_url"),
            "default_branch": data.get("default_branch"),
            "issues_enabled": data.get("issues_enabled"),
            "merge_requests_enabled": data.get("merge_requests_enabled"),
            "jobs_enabled": data.get("jobs_enabled"),
            "last_activity_at": data.get("last_activity_at"),
        },
    }


def list_merge_requests(project_id_or_path: str, state: str = "opened", limit: int = 20) -> dict[str, Any]:
    encoded = project_api_path(project_id_or_path)
    res = _request("GET", f"/projects/{encoded}/merge_requests", query={"state": state, "per_page": _limit(limit)})
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {"ok": True, "count": len(rows), "merge_requests": [_mr_summary(item) for item in rows if isinstance(item, dict)]}


def list_issues(project_id_or_path: str, state: str = "opened", limit: int = 20) -> dict[str, Any]:
    encoded = project_api_path(project_id_or_path)
    res = _request("GET", f"/projects/{encoded}/issues", query={"state": state, "per_page": _limit(limit)})
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {"ok": True, "count": len(rows), "issues": [_issue_summary(item) for item in rows if isinstance(item, dict)]}


def list_pipelines(project_id_or_path: str, ref: str = "", limit: int = 20) -> dict[str, Any]:
    encoded = project_api_path(project_id_or_path)
    query: dict[str, Any] = {"per_page": _limit(limit)}
    if ref:
        query["ref"] = ref.strip()
    res = _request("GET", f"/projects/{encoded}/pipelines", query=query)
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {
        "ok": True,
        "count": len(rows),
        "pipelines": [
            {"id": item.get("id"), "iid": item.get("iid"), "status": item.get("status"), "ref": item.get("ref"), "source": item.get("source"), "web_url": item.get("web_url"), "updated_at": item.get("updated_at")}
            for item in rows
            if isinstance(item, dict)
        ],
    }


def _mr_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "iid": item.get("iid"),
        "title": item.get("title"),
        "state": item.get("state"),
        "author": (item.get("author") or {}).get("username") if isinstance(item.get("author"), dict) else None,
        "source_branch": item.get("source_branch"),
        "target_branch": item.get("target_branch"),
        "web_url": item.get("web_url"),
        "updated_at": item.get("updated_at"),
    }


def _issue_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "iid": item.get("iid"),
        "title": item.get("title"),
        "state": item.get("state"),
        "author": (item.get("author") or {}).get("username") if isinstance(item.get("author"), dict) else None,
        "labels": item.get("labels") or [],
        "web_url": item.get("web_url"),
        "updated_at": item.get("updated_at"),
    }


def resource_provider_document() -> dict[str, Any]:
    status = gitlab_status()
    return {
        "provider_id": PROVIDER_ID,
        "label": "GitLab.com @rafagye",
        "kind": "external_development_provider",
        "capabilities": [
            "git_repos",
            "issues",
            "merge_requests",
            "ci_cd",
            "pipelines",
            "code_review_context",
            "hackathon_traceability",
            "ci_components_catalog_study",
            "ai_catalog_study",
            "duo_optional",
            "ai_gateway_optional",
        ],
        "model_provider": MODEL_PROVIDER_ID,
        "local_first": False,
        "status": "active" if status.get("auth_ok") else "configured_needs_token",
        "requires": ["GitLab access token in owner_vault", "license/capability verification before Duo/AI Gateway spend"],
        "cost_policy": "external_specialized_not_default",
        "verified_user": status.get("verified_user"),
        "updated_at": _now(),
        "registry_version": "resource_fabric_v1",
    }


def model_provider_document() -> dict[str, Any]:
    return {
        "model_provider": MODEL_PROVIDER_ID,
        "provider_id": PROVIDER_ID,
        "task_classes": ["repo_traceability", "ci_cd", "code_review_context", "merge_request_review", "hackathon_delivery"],
        "priority": 70,
        "cost_policy": "external_specialized_not_default",
        "default_enabled": False,
        "routing_note": "Never selected for generic coding/heavy_reasoning; only explicit GitLab/CI/CD/repo traceability tasks.",
        "updated_at": _now(),
        "registry_version": "model_registry_v1",
    }


def register_resource_provider(dry_run: bool = False) -> dict[str, Any]:
    provider = resource_provider_document()
    model = model_provider_document()
    if dry_run:
        return {"ok": True, "dry_run": True, "provider": provider, "model": model}
    db = mongo_store.get_db()
    now = _now()
    provider["updated_at"] = now
    model["updated_at"] = now
    db["inneros_resource_providers"].update_one({"provider_id": provider["provider_id"]}, {"$set": provider, "$setOnInsert": {"created_at": now}}, upsert=True)
    db["inneros_model_registry"].update_one({"model_provider": model["model_provider"]}, {"$set": model, "$setOnInsert": {"created_at": now}}, upsert=True)
    _audit("register_resource_provider", {"ok": True, "provider_id": PROVIDER_ID})
    return {"ok": True, "provider": provider, "model": model}


def gitlab_credit_status(register_if_missing: bool = True, dry_run: bool = False) -> dict[str, Any]:
    db = mongo_store.get_db()
    existing = list(
        db["funding_credit_accounts"].find(
            {
                "$or": [
                    {"provider": "gitlab"},
                    {"metadata.account_ref": CREDIT_ACCOUNT_REF},
                    {"name": {"$regex": "GitLab Contributor Reward", "$options": "i"}},
                ]
            },
            {"_id": 0},
        )
    )
    if existing or not register_if_missing:
        return {"ok": True, "count": len(existing), "accounts": existing, "registered_new": False}
    doc = {
        "name": CREDIT_ACCOUNT_NAME,
        "provider": "gitlab",
        "currency": "CREDITS",
        "balance": 80,
        "status": "paused",
        "metadata": {
            "account_ref": CREDIT_ACCOUNT_REF,
            "owner_hint": "@rafagye",
            "spend_policy": "not_gastable_until_expiry_rules_catalog_and_account_state_are_verified",
            "source_note": "ChatGPT handoff reported 80 Contributor Reward Credits; needs live GitLab verification.",
        },
        "source": CAPABILITY,
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "registered_new": True, "account": doc}
    created = funding_registry.save_funding_credit_account(**doc)
    return {**created, "registered_new": True}


def health_check() -> dict[str, Any]:
    status = gitlab_status()
    provider = register_resource_provider(dry_run=True)
    credits = gitlab_credit_status(register_if_missing=True, dry_run=True)
    return {
        "ok": True,
        "capability": CAPABILITY,
        "status": status,
        "provider_dry_run": provider,
        "credits_dry_run": credits,
        "ready_for_live_gitlab_calls": bool(status.get("auth_ok")),
    }
