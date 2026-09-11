"""Global Resource Fabric registry for InnerOS.

Projects request capabilities. The fabric decides whether local Intel, local AMD,
cloud burst, or another provider should satisfy the task.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from raphiia_openai import funding_registry, mongo_store
from raphiia_openai import digitalocean_amd_provider
from raphiia_openai import gemini_runtime
from raphiia_openai import local_discord_plane
from raphiia_openai import local_gitlab_plane
from raphiia_openai import assemblyai_provider

COL_PROVIDERS = "inneros_resource_providers"
COL_MODEL_REGISTRY = "inneros_model_registry"
COL_RESOURCE_LINKS = "inneros_resource_project_links"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bootstrap_global_resource_fabric(dry_run: bool = False) -> dict[str, Any]:
    providers = [
        {
            "provider_id": "local-amd-5",
            "label": "Local AMD .5",
            "kind": "local_node",
            "capabilities": ["coding", "heavy_reasoning", "gpu_inference", "tests_build"],
            "node": "192.168.1.5",
            "local_first": True,
            "status": "active",
        },
        {
            "provider_id": "local-intel-4",
            "label": "Local Intel .4",
            "kind": "local_node",
            "capabilities": ["coding", "tests_build", "browser_review", "fallback"],
            "node": "192.168.1.4",
            "local_first": True,
            "status": "active",
        },
        gemini_runtime.resource_provider_document(),
        digitalocean_amd_provider.resource_provider_document(),
        local_gitlab_plane.resource_provider_document(),
        local_discord_plane.resource_provider_document(),
        assemblyai_provider.resource_provider_document(),
    ]
    models = [
        {
            "model_provider": "local-amd",
            "provider_id": "local-amd-5",
            "task_classes": ["coding", "heavy_reasoning"],
            "priority": 10,
            "cost_policy": "local_first",
        },
        {
            "model_provider": "local-intel",
            "provider_id": "local-intel-4",
            "task_classes": ["tests_build", "browser_review", "fallback"],
            "priority": 20,
            "cost_policy": "local_first",
        },
        gemini_runtime.model_provider_document(),
        digitalocean_amd_provider.model_provider_document(),
        local_gitlab_plane.model_provider_document(),
    ]
    if dry_run:
        return {"ok": True, "dry_run": True, "providers": providers, "models": models, "funding": funding_registry.get_funding_registry_summary(limit=5)}
    db = mongo_store.get_db()
    now = _now()
    for doc in providers:
        doc = {**doc, "updated_at": now, "registry_version": "resource_fabric_v1"}
        db[COL_PROVIDERS].update_one({"provider_id": doc["provider_id"]}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    for doc in models:
        doc = {**doc, "updated_at": now, "registry_version": "model_registry_v1"}
        db[COL_MODEL_REGISTRY].update_one({"model_provider": doc["model_provider"]}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    return {"ok": True, "providers_count": len(providers), "models_count": len(models), "providers": providers, "models": models}


def resource_fabric_status(limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    return {
        "ok": True,
        "providers": list(db[COL_PROVIDERS].find({}, {"_id": 0}).sort("provider_id", 1).limit(limit)),
        "models": list(db[COL_MODEL_REGISTRY].find({}, {"_id": 0}).sort("priority", 1).limit(limit)),
        "links": list(db[COL_RESOURCE_LINKS].find({}, {"_id": 0}).sort("updated_at", -1).limit(limit)),
        "funding": funding_registry.get_funding_registry_summary(limit=5),
        "routing_policy": "local-first; cloud burst only when explicit capability/policy and approval gates are satisfied",
    }


def link_project_capability(project_id: str, capability: str, provider_id: str = "", task_id: str = "", dry_run: bool = False) -> dict[str, Any]:
    project = (project_id or "").strip()
    cap = (capability or "").strip()
    provider = (provider_id or "").strip()
    if not project or not cap:
        return {"ok": False, "error": "project_id_and_capability_required"}
    doc = {
        "project_id": project,
        "capability": cap,
        "provider_id": provider,
        "task_id": (task_id or "").strip(),
        "link_type": "capability_request",
        "updated_at": _now(),
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "link": doc}
    mongo_store.get_db()[COL_RESOURCE_LINKS].update_one(
        {"project_id": project, "capability": cap, "provider_id": provider, "task_id": doc["task_id"]},
        {"$set": doc, "$setOnInsert": {"created_at": doc["updated_at"]}},
        upsert=True,
    )
    return {"ok": True, "link": doc}


def route_resource_request(
    project_id: str,
    task_class: str,
    prefer_cloud: bool = False,
    correlation_id: str = "",
    tenant_id: str = "",
    workflow_id: str = "",
    emit_audit: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    db = mongo_store.get_db()
    models = list(db[COL_MODEL_REGISTRY].find({"task_classes": task_class}, {"_id": 0}).sort("priority", 1))
    if not models:
        bootstrap_global_resource_fabric(dry_run=False)
        models = list(db[COL_MODEL_REGISTRY].find({"task_classes": task_class}, {"_id": 0}).sort("priority", 1))
    candidates = []
    for model in models:
        if not prefer_cloud and model.get("cost_policy") == "explicit_burst_only":
            continue
        provider = db[COL_PROVIDERS].find_one({"provider_id": model.get("provider_id")}, {"_id": 0}) or {}
        candidates.append({"model": model, "provider": provider, "selection_kind": "model"})

    # Non-model capabilities (voice, messaging, browser, tools, etc.) are first-class
    # Resource Fabric resources too.  Fall back to provider capabilities when no
    # model registry entry exists for the requested task class.
    if not candidates:
        links = list(
            db[COL_RESOURCE_LINKS].find(
                {"project_id": project_id, "capability": task_class}, {"_id": 0}
            ).sort("updated_at", -1)
        )
        linked_ids = [str(row.get("provider_id") or "") for row in links if row.get("provider_id")]
        providers = list(
            db[COL_PROVIDERS].find(
                {"capabilities": task_class, "status": {"$in": ["active", "configured"]}}, {"_id": 0}
            )
        )
        for provider in providers:
            candidates.append(
                {
                    "model": None,
                    "provider": provider,
                    "selection_kind": "capability",
                    "explicit_project_link": provider.get("provider_id") in linked_ids,
                }
            )
        candidates.sort(
            key=lambda row: (
                0 if row.get("explicit_project_link") else 1,
                0 if (bool((row.get("provider") or {}).get("local_first")) != bool(prefer_cloud)) else 1,
                str((row.get("provider") or {}).get("provider_id") or ""),
            )
        )
    elif prefer_cloud:
        candidates.sort(key=lambda row: 0 if (row.get("model") or {}).get("cost_policy") == "explicit_burst_only" else 1)
    selected = candidates[0] if candidates else None
    result = {"ok": bool(selected), "project_id": project_id, "task_class": task_class, "selected": selected, "candidates": candidates}
    if emit_audit:
        try:
            from raphiia_openai import audit_fabric

            result["audit"] = audit_fabric.emit_route_decision(
                result,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                latency_ms=round((perf_counter() - started) * 1000, 3),
            )
        except Exception as exc:
            result["audit"] = {"ok": False, "error": type(exc).__name__, "message": str(exc)[:300]}
    return result
