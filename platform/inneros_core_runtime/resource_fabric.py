"""Global Resource Fabric registry for InnerOS.

Projects request capabilities. The fabric decides whether local Intel, local AMD,
cloud burst, or another provider should satisfy the task.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import funding_registry, mongo_store
from raphiia_openai import digitalocean_amd_provider
from raphiia_openai import local_discord_plane
from raphiia_openai import local_gitlab_plane
try:
    from raphiia_openai import google_extra_models
except Exception:  # optional provider
    google_extra_models = None

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
        digitalocean_amd_provider.resource_provider_document(),
        local_gitlab_plane.resource_provider_document(),
        local_discord_plane.resource_provider_document(),
    ]
    if google_extra_models is not None:
        providers.append(google_extra_models.resource_provider_document())
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
        digitalocean_amd_provider.model_provider_document(),
        local_gitlab_plane.model_provider_document(),
    ]
    if google_extra_models is not None:
        models.extend(google_extra_models.model_provider_documents())
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


def route_resource_request(project_id: str, task_class: str, prefer_cloud: bool = False) -> dict[str, Any]:
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
        candidates.append({"model": model, "provider": provider})
    if prefer_cloud:
        candidates.sort(key=lambda row: 0 if (row.get("model") or {}).get("cost_policy") == "explicit_burst_only" else 1)
    selected = candidates[0] if candidates else None
    return {"ok": bool(selected), "project_id": project_id, "task_class": task_class, "selected": selected, "candidates": candidates}
