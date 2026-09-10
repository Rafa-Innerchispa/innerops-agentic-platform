"""InnerOps product module registry and tenant-aware routing contract.

This module is deliberately infrastructure-light. It describes which commercial
InnerOps applications a tenant may enter and resolves tenant/site scope from a
server-authenticated principal. Browser parameters, recorder metadata and model
output are never allowed to choose a tenant.

Physical Guardian remains implemented in its own permanent product repository:
``Rafa-Innerchispa/inneros-physical-guardian``. InnerOps references the product;
it does not duplicate its engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet


class ProductRoutingError(RuntimeError):
    """Base error for product/module routing failures."""


class UnknownTenant(ProductRoutingError):
    pass


class UnknownSite(ProductRoutingError):
    pass


class TenantAccessDenied(ProductRoutingError):
    pass


@dataclass(frozen=True, slots=True)
class ProductModule:
    module_id: str
    name: str
    layer: str
    repository: str
    route_name: str
    description: str


@dataclass(frozen=True, slots=True)
class SiteProfile:
    site_id: str
    name: str
    recorder_models: tuple[str, ...] = ()
    edge_profile: str | None = None


@dataclass(frozen=True, slots=True)
class TenantProfile:
    tenant_id: str
    name: str
    storage_namespace: str
    enabled_modules: FrozenSet[str]
    sites: tuple[SiteProfile, ...]

    def site(self, site_id: str) -> SiteProfile:
        for site in self.sites:
            if site.site_id == site_id:
                return site
        raise UnknownSite(f"unknown_site:{self.tenant_id}:{site_id}")


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    """Server-derived identity context for portal/module routing.

    ``tenant_id`` is authoritative for customer users. ``platform_support`` is
    reserved for an InnerOS operator identity and still requires an explicit
    allowlist of support tenant IDs before cross-tenant access is possible.
    """

    principal_id: str
    tenant_id: str
    roles: FrozenSet[str]
    site_ids: FrozenSet[str] | None = None
    platform_support: bool = False
    support_tenant_ids: FrozenSet[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ModuleLaunchContext:
    module_id: str
    route_name: str
    tenant_id: str
    site_id: str | None
    storage_namespace: str


MODULES: dict[str, ProductModule] = {
    "workforce": ProductModule(
        module_id="workforce",
        name="Workforce",
        layer="InnerOps",
        repository="Rafa-Innerchispa/innerspark-workforce-ai",
        route_name="workforce",
        description="Workforce, attendance, scheduling and pre-payroll operations.",
    ),
    "physical_guardian": ProductModule(
        module_id="physical_guardian",
        name="Physical Guardian",
        layer="InnerOps",
        repository="Rafa-Innerchispa/inneros-physical-guardian",
        route_name="physical-guardian",
        description="Governed Physical AI for cameras, sensors, actions, verification and evidence.",
    ),
    "quoteops": ProductModule(
        module_id="quoteops",
        name="QuoteOps",
        layer="InnerOps",
        repository="Rafa-Innerchispa/innerops-agentic-platform",
        route_name="quoteops",
        description="Commercial sourcing, configuration and quotation operations.",
    ),
}


TENANTS: dict[str, TenantProfile] = {
    "pcdoctor": TenantProfile(
        tenant_id="pcdoctor",
        name="PC Doctor",
        storage_namespace="tenant_pcdoctor",
        enabled_modules=frozenset({"physical_guardian", "quoteops"}),
        sites=(
            SiteProfile(
                site_id="pcdoctor-lab",
                name="PC Doctor Guardian Lab",
                recorder_models=("DH-XVR5208AN-4KL-X",),
                edge_profile="home-lab-dahua",
            ),
        ),
    ),
    "bellini": TenantProfile(
        tenant_id="bellini",
        name="Torres Bellini",
        storage_namespace="tenant_bellini",
        enabled_modules=frozenset({"physical_guardian"}),
        sites=(
            SiteProfile(
                site_id="bellini-t1",
                name="Bellini Torre 1",
                recorder_models=("DH-XVR5232AN-I3",),
                edge_profile="tunnel-only",
            ),
            SiteProfile(
                site_id="bellini-t2",
                name="Bellini Torre 2",
                recorder_models=("DHI-XVR5232AN-S2",),
                edge_profile="tunnel-only",
            ),
        ),
    ),
}


def tenant_profile(tenant_id: str) -> TenantProfile:
    try:
        return TENANTS[tenant_id]
    except KeyError as exc:
        raise UnknownTenant(f"unknown_tenant:{tenant_id}") from exc


def _effective_tenant(principal: PrincipalContext, requested_tenant_id: str | None) -> TenantProfile:
    """Resolve tenant without trusting a browser-selected customer.

    Normal customer identities are hard-bound to ``principal.tenant_id``.
    InnerOS platform support may switch only to an explicitly allowlisted
    tenant. This is intentionally a layer above Guardian's own tenant RBAC;
    Guardian itself must still receive and enforce the resolved tenant/site.
    """

    target = requested_tenant_id or principal.tenant_id
    if target == principal.tenant_id:
        return tenant_profile(target)

    if not principal.platform_support or "platform_support" not in principal.roles:
        raise TenantAccessDenied("cross_tenant_denied")
    if target not in principal.support_tenant_ids:
        raise TenantAccessDenied("support_tenant_not_allowlisted")
    return tenant_profile(target)


def modules_for_principal(
    principal: PrincipalContext,
    *,
    requested_tenant_id: str | None = None,
) -> tuple[ProductModule, ...]:
    tenant = _effective_tenant(principal, requested_tenant_id)
    return tuple(MODULES[module_id] for module_id in sorted(tenant.enabled_modules))


def resolve_module_launch(
    principal: PrincipalContext,
    module_id: str,
    *,
    requested_tenant_id: str | None = None,
    requested_site_id: str | None = None,
) -> ModuleLaunchContext:
    """Build the trusted context handed from the InnerOS portal to a module."""

    tenant = _effective_tenant(principal, requested_tenant_id)
    if module_id not in tenant.enabled_modules:
        raise TenantAccessDenied(f"module_not_enabled:{tenant.tenant_id}:{module_id}")
    try:
        module = MODULES[module_id]
    except KeyError as exc:
        raise ProductRoutingError(f"unknown_module:{module_id}") from exc

    site_id: str | None = None
    if requested_site_id is not None:
        tenant.site(requested_site_id)
        if principal.site_ids is not None and tenant.tenant_id == principal.tenant_id:
            if requested_site_id not in principal.site_ids:
                raise TenantAccessDenied("site_denied")
        site_id = requested_site_id

    return ModuleLaunchContext(
        module_id=module.module_id,
        route_name=module.route_name,
        tenant_id=tenant.tenant_id,
        site_id=site_id,
        storage_namespace=tenant.storage_namespace,
    )


def portal_catalog(
    principal: PrincipalContext,
    *,
    requested_tenant_id: str | None = None,
) -> dict[str, object]:
    """Return a sanitized catalog suitable for the InnerOS/InnerOps portal UI."""

    tenant = _effective_tenant(principal, requested_tenant_id)
    modules = modules_for_principal(principal, requested_tenant_id=tenant.tenant_id)
    allowed_sites = []
    for site in tenant.sites:
        if tenant.tenant_id == principal.tenant_id and principal.site_ids is not None:
            if site.site_id not in principal.site_ids:
                continue
        allowed_sites.append(
            {
                "site_id": site.site_id,
                "name": site.name,
                "recorder_models": list(site.recorder_models),
                "edge_profile": site.edge_profile,
            }
        )

    return {
        "tenant": {"tenant_id": tenant.tenant_id, "name": tenant.name},
        "modules": [
            {
                "module_id": module.module_id,
                "name": module.name,
                "route_name": module.route_name,
                "description": module.description,
            }
            for module in modules
        ],
        "sites": allowed_sites,
    }
