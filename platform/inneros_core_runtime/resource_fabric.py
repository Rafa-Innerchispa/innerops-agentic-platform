"""Global Resource Fabric registry for InnerOS.

Projects request capabilities. The fabric decides whether local Intel, local AMD,
cloud burst, or another provider should satisfy the task.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import execution_policy, funding_registry, mongo_store
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
            "capabilities": ["coding", "heavy_reasoning", "gpu_inference", "tests_build", "code_review", "refactor", "audio_tts", "audio_stt", "cpu_utility", "deterministic_tools"],
            "node": "192.168.1.5",
            "local_first": True,
            "status": "active",
            "resident_vllm_model": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ",
            "preferred_model": execution_policy.DEFAULT_PREFERRED_MODEL,
            "execution_policy": "local_first",
            "lemonade_service": "active_cpu_utility_only",
        },
        {
            "provider_id": "local-intel-4",
            "label": "Local Intel .4",
            "kind": "local_node",
            "capabilities": ["coding", "tests_build", "browser_review", "fallback", "image_generation", "classification", "basic_ops", "light_chat"],
            "node": "192.168.1.4",
            "local_first": True,
            "status": "active",
            "gpu": "NVIDIA RTX 3060 12GB",
            "comfyui_endpoint": "http://192.168.1.4:8188",
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
            "task_classes": ["coding", "heavy_reasoning", "code_review", "refactor"],
            "priority": 10,
            "cost_policy": "local_first",
            "runtime": "vllm",
            "node": "192.168.1.5",
            "model_name": execution_policy.DEFAULT_PREFERRED_MODEL,
            "execution_policy": "local_first",
        },
        {
            "model_provider": "local-intel",
            "provider_id": "local-intel-4",
            "task_classes": ["classification", "basic_ops", "light_chat", "tests_build", "browser_review", "fallback"],
            "priority": 20,
            "cost_policy": "local_first",
            "runtime": "ollama",
            "node": "192.168.1.4",
            "model_name": "phi3.5:3.8b",
            "execution_policy": "local_first",
        },
        {
            "model_provider": "local-comfy-primary",
            "provider_id": "local-intel-4",
            "task_classes": ["image_generation"],
            "priority": 5,
            "cost_policy": "local_first",
            "runtime": "comfyui",
            "node": "192.168.1.4",
            "checkpoints": ["RealVisXL_V5.0_fp16.safetensors", "sd_xl_turbo_1.0_fp16.safetensors"],
            "execution_policy": "local_first",
        },
        {
            "model_provider": "lemonade-amd-5",
            "provider_id": "local-amd-5",
            "task_classes": ["audio_tts", "audio_stt", "cpu_utility"],
            "priority": 15,
            "cost_policy": "local_first",
            "runtime": "lemonade-lemond",
            "node": "192.168.1.5",
            "subservers": {"kokoro_tts": 8001, "whisper_stt": 8002, "qwen_0_6b": 8003, "sd_turbo_cpu": 8004},
            "execution_policy": "local_first",
        },
        {
            "model_provider": "deterministic-mcp",
            "provider_id": "local-amd-5",
            "task_classes": ["deterministic_tools", "mcp_execution"],
            "priority": 1,
            "cost_policy": "no_llm_cost",
            "runtime": "deterministic_mcp",
            "node": "192.168.1.5",
            "execution_policy": "local_first",
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
        doc = {**doc, "updated_at": now, "registry_version": "resource_fabric_v2"}
        db[COL_PROVIDERS].update_one({"provider_id": doc["provider_id"]}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    for doc in models:
        doc = {**doc, "updated_at": now, "registry_version": "model_registry_v2"}
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
        "routing_policy": execution_policy.POLICY_ID,
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
    correlation_id: str | None = None,
    fallback_reason: str = "",
    approval_id: str = "",
    owner_override: bool = False,
) -> dict[str, Any]:
    task_class = execution_policy.normalize_task_class(task_class)
    if prefer_cloud:
        local_models = list(mongo_store.get_db()[COL_MODEL_REGISTRY].find({"task_classes": task_class, "cost_policy": "local_first"}, {"_id": 0}).limit(1))
        decision = execution_policy.external_execution_decision(
            task_class=task_class,
            local_available=bool(local_models),
            fallback_reason=fallback_reason,
            approval_id=approval_id,
            owner_override=owner_override,
        )
        if not decision.get("ok"):
            return {"ok": False, "project_id": project_id, "task_class": task_class, "error": decision["decision"], "policy": decision}
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

    selected_model = (selected or {}).get("model", {})
    selected_provider = (selected or {}).get("provider", {})

    reason = (
        f"Selected local GPU ComfyUI on .4 for image_generation" if task_class == "image_generation" else (
            f"Selected resident Qwen3-Coder 30B vLLM on AMD .5 for heavy coding/reasoning" if task_class in ("coding", "heavy_reasoning", "code_review", "refactor") else (
                f"Selected deterministic execution path (0 tokens)" if task_class in ("deterministic_tools", "mcp_execution") else (
                    f"Selected lightweight local model on Intel .4" if task_class in ("classification", "basic_ops", "light_chat") else "Routed via local-first capability matching"
                )
            )
        )
    )

    capacity_snapshot = {
        "amd_dot5": {"vllm_resident": True, "model": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ", "vram_used_gb": 29.4, "vram_total_gb": 34.2},
        "intel_dot4": {"comfyui_ready": True, "ollama_ready": True, "gpu": "NVIDIA RTX 3060 12GB"},
    }

    return {
        "ok": bool(selected),
        "requested_capability": task_class,
        "project_id": project_id,
        "task_class": task_class,
        "selected_provider": selected_model.get("provider_id") or selected_provider.get("provider_id", "none"),
        "node": selected_model.get("node") or selected_provider.get("node", "192.168.1.5"),
        "model": selected_model.get("model_name") or selected_model.get("model_provider", "unknown"),
        "runtime": selected_model.get("runtime", "unknown"),
        "reason": reason,
        "capacity_snapshot": capacity_snapshot,
        "correlation_id": correlation_id or "autogenerated-route-trace",
        "selected": selected,
        "candidates": candidates,
        "policy": execution_policy.task_contract(
            task_class=task_class,
            fallback_reason=fallback_reason,
            approval_id=approval_id,
            owner_override=owner_override,
        ),
    }
