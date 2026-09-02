"""Canonical executable task envelope for InnerOS control-plane routing.

Responsibility (assignee/owner) is intentionally separate from the execution
lane.  Write-capable tasks are executable only when their project/repository
binding is verified by the Project Runtime Registry and the executor lane is
explicit.  No prose/checklist inference is performed here.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from raphiia_openai import project_runtime_registry as prr

ENVELOPE_VERSION = "task-envelope-v1"
LOCAL_EXECUTION_LANE = "local_dev_swarm"
EXECUTION_LANES = frozenset(
    {
        LOCAL_EXECUTION_LANE,
        "codex",
        "cursor",
        "antigravity",
        "gemini",
        "manual",
        "auto",
    }
)
WRITE_TASK_CLASSES = frozenset({"coding", "development", "repo_write", "implementation", "repair"})
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BASE_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_lane(value: str) -> str:
    lane = _clean(value).lower().replace("-", "_")
    aliases = {
        "dev_swarm": LOCAL_EXECUTION_LANE,
        "local": LOCAL_EXECUTION_LANE,
        "local_swarm": LOCAL_EXECUTION_LANE,
        "local_dev": LOCAL_EXECUTION_LANE,
        "anti_gravity": "antigravity",
    }
    return aliases.get(lane, lane)


def is_write_capable(task_class: str, write_capable: bool | None = None) -> bool:
    if write_capable is not None:
        return bool(write_capable)
    return _clean(task_class).lower() in WRITE_TASK_CLASSES


def _idempotency_key(*, correlation_id: str, project_id: str, repo: str, base_ref: str, task_class: str, execution_lane: str) -> str:
    raw = "|".join([correlation_id, project_id, repo, base_ref, task_class, execution_lane])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def build_task_envelope(
    *,
    project_id: str = "",
    repo: str = "",
    base_ref: str = "",
    task_class: str = "coding",
    execution_lane: str = "",
    provider_transport: str = "",
    correlation_id: str = "",
    idempotency_key: str = "",
    related_project: str = "",
    write_capable: bool | None = None,
    node: str = "primary",
) -> dict[str, Any]:
    """Build and verify a task envelope without inferring from prose.

    ``related_project`` is accepted only as a migration source when it is an
    exact owner/repository string.  Ambiguous project names remain unbound.
    """
    pid = _clean(project_id)
    full_repo = _clean(repo)
    related = _clean(related_project)
    task_kind = _clean(task_class).lower() or "coding"
    lane = normalize_lane(execution_lane)
    transport = _clean(provider_transport)
    corr = _clean(correlation_id)
    base = _clean(base_ref)
    writes = is_write_capable(task_kind, write_capable)
    binding_source = "structured"

    if not full_repo and REPO_RE.fullmatch(related):
        full_repo = related
        binding_source = "legacy_related_project_exact"

    missing: list[str] = []
    if writes:
        if not pid and not full_repo:
            missing.extend(["project_id", "repo"])
        elif not full_repo:
            missing.append("repo")
        if not base:
            missing.append("base_ref")
        if not lane:
            missing.append("execution_lane")
        if not transport:
            missing.append("provider_transport")
        if not corr:
            missing.append("correlation_id")

    if lane and lane not in EXECUTION_LANES:
        return {
            "ok": False,
            "version": ENVELOPE_VERSION,
            "binding_status": "invalid",
            "error": "execution_lane_invalid",
            "execution_lane": lane,
            "allowed_execution_lanes": sorted(EXECUTION_LANES),
            "write_capable": writes,
        }
    if lane == "auto":
        return {
            "ok": False,
            "version": ENVELOPE_VERSION,
            "binding_status": "needs_execution_lane_resolution",
            "error": "execution_lane_auto_unresolved",
            "execution_lane": lane,
            "write_capable": writes,
        }
    if base and not BASE_REF_RE.fullmatch(base):
        return {
            "ok": False,
            "version": ENVELOPE_VERSION,
            "binding_status": "invalid",
            "error": "base_ref_invalid",
            "base_ref": base,
            "write_capable": writes,
        }
    if missing:
        return {
            "ok": False,
            "version": ENVELOPE_VERSION,
            "binding_status": "needs_project_binding",
            "error": "task_envelope_missing_required_fields",
            "missing": sorted(set(missing)),
            "project_id": pid or None,
            "repo": full_repo or None,
            "base_ref": base or None,
            "task_class": task_kind,
            "execution_lane": lane or None,
            "provider_transport": transport or None,
            "correlation_id": corr or None,
            "write_capable": writes,
            "binding_source": binding_source,
        }

    resolved: dict[str, Any] = {}
    if pid or full_repo:
        try:
            resolved = prr.resolve_project(project_id=pid, repo=full_repo, node=node)
        except Exception as exc:
            resolved = {"ok": False, "error": f"registry_exception:{type(exc).__name__}"}
        if not resolved.get("ok"):
            return {
                "ok": False,
                "version": ENVELOPE_VERSION,
                "binding_status": "unverified",
                "error": "project_binding_unverified",
                "registry": resolved,
                "project_id": pid or None,
                "repo": full_repo or None,
                "base_ref": base or None,
                "task_class": task_kind,
                "execution_lane": lane or None,
                "provider_transport": transport or None,
                "correlation_id": corr or None,
                "write_capable": writes,
                "binding_source": binding_source,
            }
        project = dict(resolved.get("project") or {})
        resolved_pid = _clean(project.get("project_id"))
        resolved_repo = _clean(project.get("repo"))
        if pid and resolved_pid != pid:
            return {"ok": False, "version": ENVELOPE_VERSION, "binding_status": "unverified", "error": "project_id_registry_mismatch", "requested_project_id": pid, "resolved_project_id": resolved_pid}
        if full_repo and resolved_repo != full_repo:
            return {"ok": False, "version": ENVELOPE_VERSION, "binding_status": "unverified", "error": "repo_registry_mismatch", "requested_repo": full_repo, "resolved_repo": resolved_repo}
        pid = resolved_pid
        full_repo = resolved_repo

    idem = _clean(idempotency_key) or _idempotency_key(
        correlation_id=corr,
        project_id=pid,
        repo=full_repo,
        base_ref=base,
        task_class=task_kind,
        execution_lane=lane,
    )
    binding_status = "verified" if (not writes or resolved.get("ok")) else "unverified"
    envelope = {
        "version": ENVELOPE_VERSION,
        "binding_status": binding_status,
        "project_id": pid or None,
        "repo": full_repo or None,
        "base_ref": base or None,
        "task_class": task_kind,
        "execution_lane": lane or None,
        "provider_transport": transport or None,
        "correlation_id": corr or None,
        "idempotency_key": idem,
        "write_capable": writes,
        "binding_source": binding_source,
        "registry_node": resolved.get("node") if resolved else None,
        "project_path": resolved.get("project_path") if resolved else None,
    }
    return {"ok": binding_status == "verified", "envelope": envelope, **envelope}


def validate_local_dev_swarm_task(task: dict[str, Any], *, node: str = "primary") -> dict[str, Any]:
    """Fail closed before any local worktree is created or claimed."""
    stored = task.get("task_envelope") if isinstance(task.get("task_envelope"), dict) else {}
    lane = normalize_lane(_clean(stored.get("execution_lane") or task.get("execution_lane")))
    if lane != LOCAL_EXECUTION_LANE:
        return {
            "ok": False,
            "error": "execution_lane_not_local_dev_swarm" if lane else "execution_lane_missing",
            "execution_lane": lane or None,
        }
    result = build_task_envelope(
        project_id=_clean(stored.get("project_id") or task.get("project_id")),
        repo=_clean(stored.get("repo") or task.get("repo")),
        base_ref=_clean(stored.get("base_ref") or task.get("base_ref")),
        task_class=_clean(stored.get("task_class") or task.get("task_class") or "coding"),
        execution_lane=lane,
        provider_transport=_clean(stored.get("provider_transport") or task.get("provider_transport")),
        correlation_id=_clean(stored.get("correlation_id") or task.get("correlation_id")),
        idempotency_key=_clean(stored.get("idempotency_key") or task.get("idempotency_key")),
        related_project="",
        write_capable=bool(stored.get("write_capable", task.get("write_capable", True))),
        node=node,
    )
    if not result.get("ok"):
        return result
    return {"ok": True, "envelope": result["envelope"], "repo": result["envelope"]["repo"], "project_id": result["envelope"]["project_id"], "base_ref": result["envelope"]["base_ref"], "execution_lane": lane}
