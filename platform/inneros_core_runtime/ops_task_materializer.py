"""Canonical ops task execution materialization (repo, branch, worktree preflight).

One primary task_id owns one executable repo and one worktree path.
``related_ops`` entries are references only — never used to pick a repo.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

_GITHUB_REPO = re.compile(r"^Rafa-Innerchispa/[A-Za-z0-9_.-]+$")
_GITLAB_FORK = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")


def _payload(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("payload")
    return dict(raw) if isinstance(raw, dict) else {}


def _search_text(task: dict[str, Any]) -> str:
    parts = [
        str(task.get("title") or ""),
        str(task.get("objective") or ""),
        str(task.get("correlation_id") or ""),
    ]
    parts.extend(str(x) for x in (task.get("checklist") or [])[:12])
    return "\n".join(parts).lower()


def is_gitlab_contributor_ops_task(task: dict[str, Any]) -> bool:
    cid = str(task.get("correlation_id") or "").lower()
    if "gitlab-contributorops" in cid or cid.startswith("contributorops"):
        return True
    text = _search_text(task)
    if "contributorops" in text and "gitlab" in text:
        return True
    pl = _payload(task)
    rel = str(pl.get("related_project") or task.get("related_project") or "").lower()
    if rel == "gitlab contributorops":
        return True
    if "gitlab-org/gitlab" in text:
        return True
    return False


def _explicit_github_repo(value: str) -> str | None:
    item = (value or "").strip()
    if _GITHUB_REPO.match(item):
        return item
    return None


def _explicit_gitlab_fork(value: str) -> str | None:
    item = (value or "").strip()
    if item.startswith("Rafa-Innerchispa/"):
        return None
    if _GITLAB_FORK.match(item) and item.count("/") >= 1:
        from inneros_core_runtime import gitlab_contributor_policy as gcp

        if gcp.is_contributor_policy_repo(item) or item.endswith("/gitlab"):
            return item
    return None


def _resolve_gitlab_write_fork() -> dict[str, Any]:
    from inneros_core_runtime import gitlab_contributor_policy as gcp

    fork = gcp.resolve_authenticated_write_fork()
    if not fork.get("ok"):
        return {
            "ok": False,
            "error": "gitlab_write_fork_unavailable",
            "details": fork,
        }
    repo = str(fork.get("write_fork_project") or "").strip()
    if not repo:
        return {"ok": False, "error": "gitlab_write_fork_empty", "details": fork}
    base = str(fork.get("write_fork_default_branch") or gcp.UPSTREAM_DEFAULT_BRANCH)
    return {
        "ok": True,
        "repo": repo,
        "base_ref": base,
        "materializer_lane": "gitlab_contributor_ops",
        "fork_resolution": fork,
    }


def _local_gitlab_source_ready(repo: str) -> bool:
    from inneros_core_runtime.local_execution_plane import DEFAULT_INNEROS_CORE_ROOT

    slug = repo.replace("/", "__")
    core = Path(__import__("os").environ.get("INNEROS_CORE_ROOT", str(DEFAULT_INNEROS_CORE_ROOT))).expanduser()
    source = (core / "var" / "local_execution" / "repos" / slug).resolve()
    return source.exists() and (source / ".git").exists()


def _gitlab_fork_hint_from_related_ops(task: dict[str, Any]) -> str | None:
    """Reference-only: read explicit GitLab fork from related task payloads, never GitHub platform repos."""
    pl = _payload(task)
    related = pl.get("related_ops") or task.get("related_ops")
    if not isinstance(related, list):
        return None
    try:
        from raphiia_openai import mongo_store
        from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    except Exception:
        return None
    db = mongo_store.get_db()
    for ref_tid in related[:5]:
        tid = str(ref_tid or "").strip()
        if not tid.startswith("ops_"):
            continue
        row = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"payload": 1, "repo": 1})
        if not row:
            continue
        ref_pl = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        for candidate in (str(ref_pl.get("repo") or ""), str(row.get("executable_repo") or "")):
            fork = _explicit_gitlab_fork(candidate)
            if fork and _local_gitlab_source_ready(fork):
                return fork
    return None


def _work_branch_reference_from_related_ops(task: dict[str, Any]) -> str | None:
    """Branch hint only — never used to infer repo."""
    pl = _payload(task)
    related = pl.get("related_ops") or task.get("related_ops")
    if not isinstance(related, list) or not related:
        return None
    try:
        from raphiia_openai import mongo_store
        from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    except Exception:
        return None
    db = mongo_store.get_db()
    for ref_tid in related[:3]:
        tid = str(ref_tid or "").strip()
        if not tid.startswith("ops_"):
            continue
        row = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"work_branch": 1, "base_ref": 1})
        if not row:
            continue
        branch = str(row.get("work_branch") or "").strip()
        if branch:
            return branch
    return None


def resolve_executable_repo(task: dict[str, Any]) -> dict[str, Any]:
    tid = str(task.get("task_id") or "")
    pl = _payload(task)
    warnings: list[str] = []

    if is_gitlab_contributor_ops_task(task):
        top = str(task.get("repo") or "")
        if top and _GITHUB_REPO.match(top):
            warnings.append("ignored_contaminated_github_repo_for_gitlab_contributor_ops")
        for candidate in (
            str(pl.get("repo") or ""),
            str(_gitlab_fork_hint_from_related_ops(task) or ""),
            str(task.get("executable_repo") or ""),
        ):
            fork = _explicit_gitlab_fork(candidate)
            if fork and _local_gitlab_source_ready(fork):
                base = str(task.get("base_ref") or pl.get("base_ref") or "master")
                return {
                    "ok": True,
                    "repo": fork,
                    "base_ref": base,
                    "task_id": tid,
                    "materializer_lane": "gitlab_contributor_ops",
                    "source": "payload_or_related_gitlab_fork_reference",
                    "warnings": warnings,
                }
        gl = _resolve_gitlab_write_fork()
        if not gl.get("ok"):
            return {**gl, "task_id": tid}
        return {**gl, "task_id": tid, "warnings": warnings, "source": "gitlab_fork_policy"}

    for candidate in (
        str(task.get("executable_repo") or ""),
        str(task.get("repo") or ""),
        str(pl.get("repo") or ""),
        str(task.get("repository") or ""),
    ):
        gh = _explicit_github_repo(candidate)
        if gh:
            base = str(task.get("base_ref") or pl.get("base_ref") or "main")
            return {
                "ok": True,
                "repo": gh,
                "base_ref": base,
                "task_id": tid,
                "materializer_lane": "github",
                "source": "structured_repo",
                "warnings": warnings,
            }

    try:
        from inneros_core_runtime.dev_swarm_scheduler import _structured_repo_binding

        inferred = _structured_repo_binding(task)
        if inferred:
            base = str(task.get("base_ref") or pl.get("base_ref") or "main")
            return {
                "ok": True,
                "repo": inferred,
                "base_ref": base,
                "task_id": tid,
                "materializer_lane": "github",
                "source": "structured_binding",
                "warnings": warnings,
            }
    except Exception:
        pass

    return {
        "ok": False,
        "error": "executable_repo_unresolved",
        "task_id": tid,
        "warnings": warnings,
    }


def resolve_work_branch(task: dict[str, Any], *, repo: str, provider: str = "cursor") -> str:
    branch = str(task.get("work_branch") or "").strip()
    if branch:
        return branch
    pl = _payload(task)
    branch = str(pl.get("work_branch") or "").strip()
    if branch:
        return branch
    ref_branch = _work_branch_reference_from_related_ops(task)
    if ref_branch:
        return ref_branch
    tid = str(task.get("task_id") or "task")
    slug = tid.replace("ops_", "")
    prov = (provider or "cursor").strip().lower()
    return f"{prov}/ops-{slug}"


def materialize_ops_task_execution(task: dict[str, Any], *, provider: str = "cursor") -> dict[str, Any]:
    repo_res = resolve_executable_repo(task)
    if not repo_res.get("ok"):
        return repo_res
    repo = str(repo_res["repo"])
    base_ref = str(repo_res.get("base_ref") or "main")
    work_branch = resolve_work_branch(task, repo=repo, provider=provider)
    return {
        "ok": True,
        "task_id": str(task.get("task_id") or ""),
        "repo": repo,
        "base_ref": base_ref,
        "work_branch": work_branch,
        "materializer_lane": repo_res.get("materializer_lane"),
        "source": repo_res.get("source"),
        "warnings": list(repo_res.get("warnings") or []),
    }


def _cleanup_stale_worktree_path(worktree: Path) -> bool:
    if not worktree.exists():
        return False
    if (worktree / ".git").exists():
        return False
    try:
        shutil.rmtree(worktree)
        return True
    except OSError:
        return False


def preflight_claim_worktree(
    task: dict[str, Any],
    *,
    provider: str = "cursor",
    repair_stale: bool = True,
) -> dict[str, Any]:
    """Fail-fast before owner authorization if worktree cannot be prepared."""
    mat = materialize_ops_task_execution(task, provider=provider)
    if not mat.get("ok"):
        return {
            "ok": False,
            "error": "worktree_preflight_materialization_failed",
            "materialization": mat,
        }
    repo = str(mat["repo"])
    base_ref = str(mat["base_ref"])
    work_branch = str(mat["work_branch"])
    tid = str(task.get("task_id") or "preflight")
    correlation_id = str(task.get("correlation_id") or tid)

    from inneros_core_runtime import local_execution_plane as lep

    try:
        conf = lep._repo_config(repo)
    except Exception as exc:
        return {
            "ok": False,
            "error": "worktree_preflight_repo_not_allowlisted",
            "repo": repo,
            "detail": str(exc),
            "materialization": mat,
        }

    source = Path(str(conf.get("source_path") or "")).expanduser().resolve()
    if not source.exists() or not (source / ".git").exists():
        return {
            "ok": False,
            "error": "worktree_preflight_source_repo_missing",
            "repo": repo,
            "source_path": str(source),
            "materialization": mat,
        }

    worktree = Path(lep._worktree_path(repo, work_branch, conf))
    if repair_stale and worktree.exists() and not (worktree / ".git").exists():
        cleaned = _cleanup_stale_worktree_path(worktree)
        mat = {**mat, "stale_worktree_cleaned": cleaned, "stale_worktree_path": str(worktree)}

    probe = lep.create_worktree(
        repo,
        base_ref,
        work_branch,
        provider,
        tid,
        correlation_id,
        f"preflight-{tid}",
    )
    if not probe.get("ok"):
        return {
            "ok": False,
            "error": "worktree_preflight_create_failed",
            "repo": repo,
            "work_branch": work_branch,
            "materialization": mat,
            "probe": probe,
        }
    return {
        "ok": True,
        "materialization": mat,
        "worktree": str(probe.get("worktree") or worktree),
        "probe": {"ok": True, "idempotent": probe.get("idempotent"), "verified_exists": probe.get("verified_exists")},
    }


def persist_materialization(db, task_id: str, mat: dict[str, Any]) -> None:
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL

    if not mat.get("ok"):
        return
    db[OPS_TASKS_COL].update_one(
        {"task_id": task_id},
        {
            "$set": {
                "executable_repo": mat.get("repo"),
                "repo": mat.get("repo"),
                "base_ref": mat.get("base_ref"),
                "work_branch": mat.get("work_branch"),
                "execution_materializer_lane": mat.get("materializer_lane"),
                "execution_materializer_source": mat.get("source"),
                "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            },
            "$unset": {"claim_error": ""},
        },
    )


def authorization_blockers(task: dict[str, Any], *, provider: str = "cursor") -> dict[str, Any]:
    """Run preflight; suitable before setting owner_authorized_at."""
    pf = preflight_claim_worktree(task, provider=provider)
    if pf.get("ok"):
        return {"ok": True, "preflight": pf}
    return {
        "ok": False,
        "error": pf.get("error"),
        "blocker": True,
        "preflight": pf,
        "message": (
            "No se puede preparar worktree; corrige repo/registry/source antes de pedir autorización owner."
        ),
    }
