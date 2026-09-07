"""Compatibility-safe local model manager surface.

This module preserves the MCP contract for local_model_* tools after the
runtime moved model routing into local_model_router. Expensive or mutating
actions default to dry-run/fail-closed so agents can discover capability without
silently starting downloads, deleting models, or restarting vLLM.
"""

from __future__ import annotations

import time
from typing import Any

from raphiia_openai import local_model_router, mongo_store

CAPABILITY = "local_model_manager"
VERSION = "local_model_manager_v2_compat"
JOBS_COL = "ralfia_local_model_jobs"
DEFAULT_PROVIDER = "local-amd-5"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _job_id(prefix: str = "lmjob") -> str:
    return f"{prefix}_{_now_ms()}"


def _state() -> dict[str, Any]:
    try:
        state = mongo_store.get_coordination_state("local_model_router")
        if state.get("ok") and isinstance(state.get("state"), dict):
            return state["state"]
    except Exception:
        pass
    return {}


def _record_job(job: dict[str, Any]) -> None:
    try:
        mongo_store.get_db()[JOBS_COL].update_one(
            {"job_id": job["job_id"]},
            {"$set": job, "$setOnInsert": {"created_at_ms": _now_ms()}},
            upsert=True,
        )
    except Exception:
        pass


def local_model_health() -> dict[str, Any]:
    result = local_model_router.local_model_health()
    result.setdefault("capability", CAPABILITY)
    result["manager_version"] = VERSION
    return result


def local_model_catalog_search(
    query: str,
    source: str = "huggingface",
    filters: dict[str, Any] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    filters = filters or {}
    return {
        "ok": True,
        "capability": CAPABILITY,
        "manager_version": VERSION,
        "source": source,
        "query": query,
        "filters": filters,
        "limit": max(1, min(int(limit or 10), 50)),
        "results": [],
        "status": "DISCOVERY_NOT_CONFIGURED",
        "reason": "Catalog web search is not performed by the compatibility manager; use curated model registry or owner-approved search flow.",
    }


def local_model_preflight(
    model_ref: str,
    node: str = "amd",
    backend: str = "vllm",
    quantization: str = "",
    revision: str = "",
) -> dict[str, Any]:
    health = local_model_health()
    return {
        "ok": True,
        "capability": CAPABILITY,
        "manager_version": VERSION,
        "model_ref": model_ref,
        "node": node,
        "backend": backend,
        "quantization": quantization,
        "revision": revision,
        "health": health,
        "dry_run": True,
        "ready_for_owner_approval": bool(model_ref),
    }


def local_model_download(
    model_ref: str,
    node: str = "amd",
    revision: str = "",
    quantization: str = "",
    target_store: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    job = {
        "job_id": _job_id(),
        "kind": "download",
        "model_ref": model_ref,
        "node": node,
        "revision": revision,
        "quantization": quantization,
        "target_store": target_store,
        "status": "DRY_RUN" if dry_run else "BLOCKED_OWNER_APPROVAL_REQUIRED",
        "dry_run": dry_run,
        "manager_version": VERSION,
    }
    _record_job(job)
    return {"ok": True, "capability": CAPABILITY, **job}


def local_model_download_status(job_id: str) -> dict[str, Any]:
    try:
        row = mongo_store.get_db()[JOBS_COL].find_one({"job_id": job_id}, {"_id": 0})
    except Exception:
        row = None
    return {
        "ok": True,
        "capability": CAPABILITY,
        "manager_version": VERSION,
        "job_id": job_id,
        "job": row,
        "status": (row or {}).get("status") or "unknown_job",
    }


def local_model_worker_start(job_id: str = "", node: str = "amd") -> dict[str, Any]:
    return {
        "ok": False,
        "capability": CAPABILITY,
        "manager_version": VERSION,
        "status": "NOT_READY_OWNER_APPROVAL_REQUIRED",
        "job_id": job_id,
        "node": node,
        "reason": "Compatibility surface does not start workers; use supervised systemd/vLLM runbook.",
    }


def local_model_list(node: str = "", backend: str = "") -> dict[str, Any]:
    health = local_model_health()
    return {
        "ok": True,
        "capability": CAPABILITY,
        "manager_version": VERSION,
        "node": node,
        "backend": backend,
        "models": health.get("models") or [],
        "health": health,
    }


def local_model_serve(
    model_ref: str,
    node: str = "amd",
    backend: str = "vllm",
    alias: str = "",
    context_length: int = 8192,
    gpu_memory_utilization: float = 0.85,
    dry_run: bool = True,
) -> dict[str, Any]:
    return {
        "ok": True if dry_run else False,
        "capability": CAPABILITY,
        "manager_version": VERSION,
        "status": "DRY_RUN" if dry_run else "BLOCKED_OWNER_APPROVAL_REQUIRED",
        "model_ref": model_ref,
        "node": node,
        "backend": backend,
        "alias": alias or model_ref,
        "context_length": context_length,
        "gpu_memory_utilization": gpu_memory_utilization,
        "dry_run": dry_run,
    }


def local_model_runtime_status(node: str = "amd", backend: str = "vllm") -> dict[str, Any]:
    return {"ok": True, "capability": CAPABILITY, "manager_version": VERSION, "node": node, "backend": backend, "health": local_model_health()}


def local_model_stop(alias: str = "", model_ref: str = "", node: str = "amd") -> dict[str, Any]:
    return {"ok": False, "capability": CAPABILITY, "manager_version": VERSION, "status": "BLOCKED_OWNER_APPROVAL_REQUIRED", "alias": alias, "model_ref": model_ref, "node": node}


def local_model_delete(model_ref: str, node: str = "amd", dry_run: bool = True) -> dict[str, Any]:
    return {"ok": True if dry_run else False, "capability": CAPABILITY, "manager_version": VERSION, "status": "DRY_RUN" if dry_run else "BLOCKED_OWNER_APPROVAL_REQUIRED", "model_ref": model_ref, "node": node, "dry_run": dry_run}


def local_model_benchmark(
    model_ref: str = "",
    alias: str = "",
    prompt_suite: str = "format_contract",
    task_class: str = "coding",
    repo_context_ref: str = "",
) -> dict[str, Any]:
    return {
        "ok": True,
        "capability": CAPABILITY,
        "manager_version": VERSION,
        "status": "CONTRACT_ONLY",
        "model_ref": model_ref,
        "alias": alias,
        "prompt_suite": prompt_suite,
        "task_class": task_class,
        "repo_context_ref": repo_context_ref,
        "health": local_model_health(),
    }


def local_model_set_default(task_class: str, model_ref: str, provider_id: str = DEFAULT_PROVIDER) -> dict[str, Any]:
    setter = getattr(local_model_router, "set_default_model", None)
    if callable(setter):
        return setter(task_class=task_class, model_ref=model_ref, provider_id=provider_id)
    return {
        "ok": False,
        "capability": CAPABILITY,
        "manager_version": VERSION,
        "status": "NOT_READY_BACKEND_REMOVED",
        "task_class": task_class,
        "model_ref": model_ref,
        "provider_id": provider_id,
        "reason": "The current local_model_router does not expose set_default_model.",
    }


def local_model_router_status(project_id: str = "", task_class: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        "capability": CAPABILITY,
        "manager_version": VERSION,
        "project_id": project_id,
        "task_class": task_class,
        "state": _state(),
        "health": local_model_health(),
    }
