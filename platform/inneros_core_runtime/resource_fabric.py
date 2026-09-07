"""Global Resource Fabric registry for InnerOS.

Projects request capabilities. The fabric decides whether local Intel, local AMD,
cloud burst, or another provider should satisfy the task.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import funding_registry, mongo_store
from raphiia_openai import digitalocean_amd_provider
from raphiia_openai import gemini_runtime
from raphiia_openai import local_discord_plane
from raphiia_openai import local_gitlab_plane

COL_PROVIDERS = "inneros_resource_providers"
COL_MODEL_REGISTRY = "inneros_model_registry"
COL_RESOURCE_LINKS = "inneros_resource_project_links"
COL_PROVIDER_INSTANCES = "inneros_provider_instances"

PROVIDER_ROUTING_REASON_CODES = [
    "local_first",
    "capacity_available",
    "provider_required",
    "host_affinity",
    "repo_locality",
    "quality_gate",
    "fallback",
    "manual_session_required",
]


def provider_instance_schema() -> dict[str, Any]:
    return {
        "provider_instance_id": "provider.host alias, for example codex.amd5",
        "host": "intel4|amd5",
        "provider": "codex|cursor|antigravity|qwen|local",
        "installed": "bool|UNKNOWN",
        "authenticated": "bool|UNKNOWN|not_required",
        "headless_ready": "bool|UNKNOWN",
        "inneros_dispatchable": "bool",
        "account_profile": "primary|secondary|service|not_applicable|UNKNOWN",
        "usage_available": "object with status UNKNOWN when unsupported",
        "last_heartbeat": "ISO-8601|null",
        "current_task": "task_id|null",
        "repo_lock": "lock_id|null",
        "model_runtime": "runtime/model description without secrets",
        "auth_mode": "chatgpt_account|api_key|local_runtime|none|UNKNOWN",
        "reason_codes": "list[str]",
    }


def canonical_development_provider_instances() -> list[dict[str, Any]]:
    unknown_usage = {"status": "UNKNOWN", "reason": "no_supported_read_api"}
    manual = ["manual_session_required"]
    local = ["local_first", "capacity_available"]
    return [
        {
            "provider_instance_id": "codex.amd5",
            "host": "amd5",
            "provider": "codex",
            "installed": "UNKNOWN",
            "authenticated": "UNKNOWN",
            "headless_ready": "UNKNOWN",
            "inneros_dispatchable": False,
            "account_profile": "secondary",
            "usage_available": unknown_usage,
            "last_heartbeat": None,
            "current_task": None,
            "repo_lock": None,
            "model_runtime": "Codex CLI/session on AMD host when manually available",
            "auth_mode": "chatgpt_account",
            "reason_codes": manual,
        },
        {
            "provider_instance_id": "codex.intel4",
            "host": "intel4",
            "provider": "codex",
            "installed": True,
            "authenticated": "UNKNOWN",
            "headless_ready": "UNKNOWN",
            "inneros_dispatchable": False,
            "account_profile": "primary",
            "usage_available": unknown_usage,
            "last_heartbeat": None,
            "current_task": None,
            "repo_lock": None,
            "model_runtime": "codex-cli; manual session unless supported headless dispatcher proves readiness",
            "auth_mode": "chatgpt_account",
            "reason_codes": manual,
        },
        {
            "provider_instance_id": "cursor.amd5",
            "host": "amd5",
            "provider": "cursor",
            "installed": "UNKNOWN",
            "authenticated": "UNKNOWN",
            "headless_ready": "UNKNOWN",
            "inneros_dispatchable": False,
            "account_profile": "UNKNOWN",
            "usage_available": unknown_usage,
            "last_heartbeat": None,
            "current_task": None,
            "repo_lock": None,
            "model_runtime": "Cursor IDE/CLI if present; manual session required until headless contract exists",
            "auth_mode": "chatgpt_account",
            "reason_codes": manual,
        },
        {
            "provider_instance_id": "cursor.intel4",
            "host": "intel4",
            "provider": "cursor",
            "installed": "UNKNOWN",
            "authenticated": "UNKNOWN",
            "headless_ready": "UNKNOWN",
            "inneros_dispatchable": False,
            "account_profile": "UNKNOWN",
            "usage_available": unknown_usage,
            "last_heartbeat": None,
            "current_task": None,
            "repo_lock": None,
            "model_runtime": "Cursor IDE/CLI if present; manual session required until headless contract exists",
            "auth_mode": "chatgpt_account",
            "reason_codes": manual,
        },
        {
            "provider_instance_id": "antigravity.amd5",
            "host": "amd5",
            "provider": "antigravity",
            "installed": "UNKNOWN",
            "authenticated": "UNKNOWN",
            "headless_ready": "UNKNOWN",
            "inneros_dispatchable": False,
            "account_profile": "UNKNOWN",
            "usage_available": unknown_usage,
            "last_heartbeat": None,
            "current_task": None,
            "repo_lock": None,
            "model_runtime": "Antigravity IDE/CLI if present; manual session required until headless contract exists",
            "auth_mode": "chatgpt_account",
            "reason_codes": manual,
        },
        {
            "provider_instance_id": "antigravity.intel4",
            "host": "intel4",
            "provider": "antigravity",
            "installed": "UNKNOWN",
            "authenticated": "UNKNOWN",
            "headless_ready": "UNKNOWN",
            "inneros_dispatchable": False,
            "account_profile": "UNKNOWN",
            "usage_available": unknown_usage,
            "last_heartbeat": None,
            "current_task": None,
            "repo_lock": None,
            "model_runtime": "Antigravity IDE/CLI if present; manual session required until headless contract exists",
            "auth_mode": "chatgpt_account",
            "reason_codes": manual,
        },
        {
            "provider_instance_id": "qwen.amd5",
            "host": "amd5",
            "provider": "qwen",
            "installed": True,
            "authenticated": "not_required",
            "headless_ready": True,
            "inneros_dispatchable": True,
            "account_profile": "not_applicable",
            "usage_available": {"status": "UNMETERED_LOCAL"},
            "last_heartbeat": None,
            "current_task": None,
            "repo_lock": None,
            "model_runtime": "vLLM ROCm10, QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ",
            "auth_mode": "local_runtime",
            "reason_codes": local,
        },
        {
            "provider_instance_id": "local.intel4",
            "host": "intel4",
            "provider": "local",
            "installed": True,
            "authenticated": "not_required",
            "headless_ready": True,
            "inneros_dispatchable": True,
            "account_profile": "not_applicable",
            "usage_available": {"status": "UNMETERED_LOCAL"},
            "last_heartbeat": None,
            "current_task": None,
            "repo_lock": None,
            "model_runtime": "Local Execution Plane for git/tests/build orchestration",
            "auth_mode": "local_runtime",
            "reason_codes": local,
        },
    ]


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
    provider_instances = canonical_development_provider_instances()
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "providers": providers,
            "models": models,
            "provider_instance_schema": provider_instance_schema(),
            "provider_instances": provider_instances,
            "funding": funding_registry.get_funding_registry_summary(limit=5),
        }
    db = mongo_store.get_db()
    now = _now()
    for doc in providers:
        doc = {**doc, "updated_at": now, "registry_version": "resource_fabric_v1"}
        db[COL_PROVIDERS].update_one({"provider_id": doc["provider_id"]}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    for doc in models:
        doc = {**doc, "updated_at": now, "registry_version": "model_registry_v1"}
        db[COL_MODEL_REGISTRY].update_one({"model_provider": doc["model_provider"]}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    for doc in provider_instances:
        doc = {**doc, "updated_at": now, "registry_version": "provider_instance_v1"}
        db[COL_PROVIDER_INSTANCES].update_one(
            {"provider_instance_id": doc["provider_instance_id"]},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
    return {
        "ok": True,
        "providers_count": len(providers),
        "models_count": len(models),
        "provider_instances_count": len(provider_instances),
        "providers": providers,
        "models": models,
        "provider_instances": provider_instances,
    }


def resource_fabric_status(limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    instances = list(db[COL_PROVIDER_INSTANCES].find({}, {"_id": 0}).sort("provider_instance_id", 1).limit(limit))
    if not instances:
        instances = canonical_development_provider_instances()[:limit]
    return {
        "ok": True,
        "providers": list(db[COL_PROVIDERS].find({}, {"_id": 0}).sort("provider_id", 1).limit(limit)),
        "models": list(db[COL_MODEL_REGISTRY].find({}, {"_id": 0}).sort("priority", 1).limit(limit)),
        "provider_instance_schema": provider_instance_schema(),
        "provider_instances": instances,
        "links": list(db[COL_RESOURCE_LINKS].find({}, {"_id": 0}).sort("updated_at", -1).limit(limit)),
        "funding": funding_registry.get_funding_registry_summary(limit=5),
        "routing_policy": "local-first; host-specific provider instances; cloud burst only when explicit capability/policy and approval gates are satisfied",
        "reason_codes": PROVIDER_ROUTING_REASON_CODES,
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
    reason_codes = ["provider_required"] if prefer_cloud else ["local_first"]
    if selected:
        reason_codes.append("capacity_available")
    else:
        reason_codes.append("fallback")
    return {
        "ok": bool(selected),
        "project_id": project_id,
        "task_class": task_class,
        "selected": selected,
        "candidates": candidates,
        "reason_codes": reason_codes,
    }


def route_development_provider(
    project_id: str,
    task_class: str = "coding",
    preferred_instance: str = "",
    host_affinity: str = "",
) -> dict[str, Any]:
    instances = canonical_development_provider_instances()
    if preferred_instance:
        instances = [item for item in instances if item["provider_instance_id"] == preferred_instance]
    if host_affinity:
        instances = [item for item in instances if item["host"] == host_affinity]
    candidates = []
    for item in instances:
        reason_codes = list(item.get("reason_codes") or [])
        if preferred_instance:
            reason_codes.append("provider_required")
        if host_affinity:
            reason_codes.append("host_affinity")
        if item.get("inneros_dispatchable") is not True:
            if "manual_session_required" not in reason_codes:
                reason_codes.append("manual_session_required")
            candidates.append({**item, "eligible": False, "reason_codes": reason_codes})
            continue
        candidates.append({**item, "eligible": True, "reason_codes": reason_codes})
    eligible = [item for item in candidates if item.get("eligible")]
    priority = {"qwen.amd5": 0, "local.intel4": 1}
    eligible.sort(key=lambda item: priority.get(str(item.get("provider_instance_id")), 50))
    selected = eligible[0] if eligible else None
    route_codes = list(selected.get("reason_codes") if selected else ["fallback", "manual_session_required"])
    return {
        "ok": bool(selected),
        "project_id": (project_id or "").strip(),
        "task_class": (task_class or "coding").strip(),
        "selected": selected,
        "candidates": candidates,
        "reason_codes": route_codes,
        "truth_boundary": "Installed/authenticated/headless states remain UNKNOWN unless verified by a supported host probe; no secrets are stored.",
    }
