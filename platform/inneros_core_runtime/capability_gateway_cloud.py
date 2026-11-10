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
