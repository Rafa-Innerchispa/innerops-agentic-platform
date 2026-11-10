"""Capability Gateway Cloud Infrastructure Provider registration.

Exposes Vultr, DigitalOcean, Nebius NVIDIA, and local AMD capabilities
to InnerOS capability router, capability_search, and MCP runtime.
"""

from __future__ import annotations

from typing import Any, Dict


def register_cloud_capabilities(register_capability=None) -> None:
    if register_capability is None:
        from inneros_core_runtime import capability_gateway as cg
        register_capability = cg.register_capability
    from inneros_core_runtime import cloud_provider_fabric

    # 1. Cloud Providers List
    register_capability(
        manifest={
            "capability_id": "cloud.providers.list.v1",
            "version": "1.0.0",
            "title": "List Cloud & Compute Providers",
            "description": "Lists all configured cloud infrastructure and compute providers (Vultr, DigitalOcean, Nebius, AMD).",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["cloud", "vultr", "digitalocean", "nebius", "nvidia", "amd", "providers", "compute"],
        },
        handler=lambda params, context: cloud_provider_fabric.list_providers()
    )

    # 2. Cloud Provider Status
    register_capability(
        manifest={
            "capability_id": "cloud.provider.status.v1",
            "version": "1.0.0",
            "title": "Cloud Provider Status & Health",
            "description": "Returns detailed connectivity, account and health status for Vultr, DigitalOcean, Nebius, or AMD.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["cloud", "vultr", "digitalocean", "nebius", "nvidia", "status", "health"],
        },
        handler=lambda params, context: cloud_provider_fabric.get_provider_status(provider_id=params.get("provider_id", "vultr-cloud"))
    )

    # 3. Cloud Instances List
    register_capability(
        manifest={
            "capability_id": "cloud.instances.list.v1",
            "version": "1.0.0",
            "title": "List Active Cloud VM Instances",
            "description": "Lists active instances, droplets, specs, IPs, and statuses across cloud providers.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["cloud", "vultr", "digitalocean", "instances", "vms", "droplets", "inventory"],
        },
        handler=lambda params, context: cloud_provider_fabric.list_instances(provider_id=params.get("provider_id"))
    )

    # 4. Cloud Instance Plan (Dry-Run)
    register_capability(
        manifest={
            "capability_id": "cloud.instance.plan.v1",
            "version": "1.0.0",
            "title": "Plan Cloud Instance Provisioning (Dry-Run)",
            "description": "Generates a zero-spend dry-run configuration and pricing estimate for a requested cloud VM.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "dry_run",
            "keywords": ["cloud", "vultr", "digitalocean", "plan", "dry_run", "pricing", "specs", "estimate"],
        },
        handler=lambda params, context: cloud_provider_fabric.plan_instance(**params)
    )

    # 5. Cloud Instance Create (Gated)
    register_capability(
        manifest={
            "capability_id": "cloud.instance.create.v1",
            "version": "1.0.0",
            "title": "Create Cloud Instance (Gated)",
            "description": "Provisions a cloud instance. Strictly dry_run=True by default; requires explicit owner approval.",
            "domain": "cloud_infrastructure",
            "risk_class": "high",
            "mode": "gated_mutation",
            "keywords": ["cloud", "vultr", "digitalocean", "create", "provision", "deploy"],
        },
        handler=lambda params, context: cloud_provider_fabric.create_instance(**params)
    )

    # 6. Cloud Credits Status
    register_capability(
        manifest={
            "capability_id": "cloud.credits.status.v1",
            "version": "1.0.0",
            "title": "Cloud Credits and Billing Status",
            "description": "Aggregates verified balances, promo credits, and sources across Vultr, DigitalOcean, Nebius, and AMD.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["cloud", "vultr", "digitalocean", "nebius", "nvidia", "credits", "balance", "billing"],
        },
        handler=lambda params, context: cloud_provider_fabric.get_credits_status()
    )

    # 7. Cloud Pricing Compare
    register_capability(
        manifest={
            "capability_id": "cloud.pricing.compare.v1",
            "version": "1.0.0",
            "title": "Compare Cloud Compute Pricing",
            "description": "Compares compute and RAM pricing across Vultr, DigitalOcean, and local AMD hardware.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["cloud", "vultr", "digitalocean", "amd", "pricing", "compare", "cost"],
        },
        handler=lambda params, context: cloud_provider_fabric.compare_pricing(specs=params.get("specs", {}))
    )

    # 8. Vultr Serverless Inference Chat
    register_capability(
        manifest={
            "capability_id": "cloud.vultr.inference.chat.v1",
            "version": "1.0.0",
            "title": "Vultr Serverless Inference Chat Completion",
            "description": "Serverless chat completions with DeepSeek, Qwen 3.8, GLM, MiniMax via Vultr promotional credits.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["vultr", "inference", "chat", "deepseek", "qwen", "llm", "cloud_burst"],
        },
        handler=lambda params, context: __import__("inneros_core_runtime.vultr_inference_provider", fromlist=["vultr_inference_provider"]).chat_completion(
            messages=params.get("messages", []),
            model=params.get("model", "deepseek-v4.1-flash-1017"),
            max_tokens=params.get("max_tokens", 512),
        )
    )

    # 9. Vultr Serverless Inference Embeddings
    register_capability(
        manifest={
            "capability_id": "cloud.vultr.inference.embeddings.v1",
            "version": "1.0.0",
            "title": "Vultr Serverless Dense Embeddings",
            "description": "Generate dense text embeddings using Qwen3-Embedding-4B on Vultr.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["vultr", "inference", "embeddings", "rag", "qwen", "vector"],
        },
        handler=lambda params, context: __import__("inneros_core_runtime.vultr_inference_provider", fromlist=["vultr_inference_provider"]).embeddings(
            texts=params.get("texts", []),
            model=params.get("model", "qwen3-embedding-4b"),
        )
    )

    # 10. Vultr Serverless Inference Rerank
    register_capability(
        manifest={
            "capability_id": "cloud.vultr.inference.rerank.v1",
            "version": "1.0.0",
            "title": "Vultr Serverless Cross-Encoder Reranking",
            "description": "Rerank candidate documents using BGE Reranker v2 M3 on Vultr.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["vultr", "inference", "rerank", "bge", "rag", "search"],
        },
        handler=lambda params, context: __import__("inneros_core_runtime.vultr_inference_provider", fromlist=["vultr_inference_provider"]).rerank(
            query=params.get("query", ""),
            documents=params.get("documents", []),
            top_n=params.get("top_n", 5),
        )
    )

    # 11. Vultr Serverless Models Catalog
    register_capability(
        manifest={
            "capability_id": "cloud.vultr.inference.models.v1",
            "version": "1.0.0",
            "title": "Vultr Serverless Models Catalog",
            "description": "List all 33+ available serverless models on Vultr Serverless Inference.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["vultr", "inference", "models", "catalog"],
        },
        handler=lambda params, context: __import__("inneros_core_runtime.vultr_inference_provider", fromlist=["vultr_inference_provider"]).list_models()
    )

    # 12. Vultr Serverless Inference Status
    register_capability(
        manifest={
            "capability_id": "cloud.vultr.inference.status.v1",
            "version": "1.0.0",
            "title": "Vultr Serverless Inference Status & Credits",
            "description": "Check connection, models, budget cap and promotional credits for Vultr inference.",
            "domain": "cloud_infrastructure",
            "risk_class": "low",
            "mode": "read_only",
            "keywords": ["vultr", "inference", "status", "credits", "budget"],
        },
        handler=lambda params, context: __import__("inneros_core_runtime.vultr_inference_provider", fromlist=["vultr_inference_provider"]).status()
    )
