import sys
from pathlib import Path


PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime.product_modules import (
    MODULES,
    TENANTS,
    PrincipalContext,
    TenantAccessDenied,
    modules_for_principal,
    portal_catalog,
    resolve_module_launch,
)


def test_physical_guardian_is_first_class_innerops_module() -> None:
    guardian = MODULES["physical_guardian"]
    assert guardian.layer == "InnerOps"
    assert guardian.repository == "Rafa-Innerchispa/inneros-physical-guardian"
    assert guardian.route_name == "physical-guardian"


def test_pcdoctor_lab_and_bellini_are_separate_tenants() -> None:
    pcdoctor = TENANTS["pcdoctor"]
    bellini = TENANTS["bellini"]

    assert pcdoctor.storage_namespace != bellini.storage_namespace
    assert [site.site_id for site in pcdoctor.sites] == ["pcdoctor-lab"]
    assert [site.site_id for site in bellini.sites] == ["bellini-t1", "bellini-t2"]
    assert bellini.sites[0].recorder_models == ("DH-XVR5232AN-I3",)
    assert bellini.sites[1].recorder_models == ("DHI-XVR5232AN-S2",)


def test_customer_cannot_switch_tenant_from_browser_parameter() -> None:
    principal = PrincipalContext(
        principal_id="pcdoctor-user",
        tenant_id="pcdoctor",
        roles=frozenset({"admin"}),
    )

    try:
        resolve_module_launch(
            principal,
            "physical_guardian",
            requested_tenant_id="bellini",
            requested_site_id="bellini-t1",
        )
    except TenantAccessDenied as exc:
        assert str(exc) == "cross_tenant_denied"
    else:
        raise AssertionError("cross-tenant switch should fail closed")


def test_bellini_user_sees_only_bellini_sites() -> None:
    principal = PrincipalContext(
        principal_id="bellini-operator",
        tenant_id="bellini",
        roles=frozenset({"operator"}),
        site_ids=frozenset({"bellini-t1"}),
    )

    catalog = portal_catalog(principal)
    assert catalog["tenant"]["tenant_id"] == "bellini"
    assert [site["site_id"] for site in catalog["sites"]] == ["bellini-t1"]
    assert [module["module_id"] for module in catalog["modules"]] == ["physical_guardian"]


def test_site_scope_fails_closed_inside_same_tenant() -> None:
    principal = PrincipalContext(
        principal_id="bellini-t1-viewer",
        tenant_id="bellini",
        roles=frozenset({"viewer"}),
        site_ids=frozenset({"bellini-t1"}),
    )

    try:
        resolve_module_launch(
            principal,
            "physical_guardian",
            requested_site_id="bellini-t2",
        )
    except TenantAccessDenied as exc:
        assert str(exc) == "site_denied"
    else:
        raise AssertionError("site restriction should fail closed")


def test_internal_support_switch_requires_explicit_tenant_allowlist() -> None:
    support = PrincipalContext(
        principal_id="inneros-support",
        tenant_id="pcdoctor",
        roles=frozenset({"platform_support"}),
        platform_support=True,
        support_tenant_ids=frozenset({"bellini"}),
    )

    launch = resolve_module_launch(
        support,
        "physical_guardian",
        requested_tenant_id="bellini",
        requested_site_id="bellini-t2",
    )
    assert launch.tenant_id == "bellini"
    assert launch.site_id == "bellini-t2"
    assert launch.storage_namespace == "tenant_bellini"


def test_pcdoctor_catalog_exposes_guardian_and_quoteops() -> None:
    principal = PrincipalContext(
        principal_id="pcdoctor-owner",
        tenant_id="pcdoctor",
        roles=frozenset({"owner"}),
    )

    module_ids = {module.module_id for module in modules_for_principal(principal)}
    assert module_ids == {"physical_guardian", "quoteops"}

    catalog = portal_catalog(principal)
    assert catalog["tenant"] == {"tenant_id": "pcdoctor", "name": "PC Doctor"}
    assert catalog["sites"][0]["site_id"] == "pcdoctor-lab"
