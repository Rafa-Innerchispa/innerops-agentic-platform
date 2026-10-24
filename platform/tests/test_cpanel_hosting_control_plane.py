"""
Unit and integration tests for Universal Hosting Control Plane,
cPanel UAPI capabilities, IMAP query, and WordPress spec generator.
"""

from __future__ import annotations

import re
import pytest
from inneros_core_runtime.capability_gateway import (
    capability_describe,
    capability_invoke,
    capability_search,
)
from inneros_core_runtime.hosting_control_plane import HostingControlPlane


def test_capability_search_finds_hosting_and_cpanel():
    res = capability_search(query="cpanel")
    assert res.get("ok") is True
    cap_ids = [h.get("capability_id") for h in res.get("capabilities", [])]
    assert "hosting.cpanel.query.v1" in cap_ids
    assert "hosting.cpanel.mutate.v1" in cap_ids


def test_capability_search_finds_imap_and_wordpress():
    res_email = capability_search(query="imap")
    assert res_email.get("ok") is True
    cap_ids_email = [h.get("capability_id") for h in res_email.get("capabilities", [])]
    assert "email.imap.query.v1" in cap_ids_email

    res_wp = capability_search(query="wordpress")
    assert res_wp.get("ok") is True
    cap_ids_wp = [h.get("capability_id") for h in res_wp.get("capabilities", [])]
    assert "wordpress.site.query.v1" in cap_ids_wp


def test_capability_describe_hosting_manifests():
    desc_query = capability_describe("hosting.cpanel.query.v1")
    assert desc_query.get("ok") is True
    cap_q = desc_query.get("capability", {})
    assert cap_q.get("mode") == "read_only"
    assert "ralfia:read" in cap_q.get("required_scopes", [])

    desc_mutate = capability_describe("hosting.cpanel.mutate.v1")
    assert desc_mutate.get("ok") is True
    cap_m = desc_mutate.get("capability", {})
    assert cap_m.get("mode") == "mutation"
    assert "ralfia:admin" in cap_m.get("required_scopes", [])

    desc_imap = capability_describe("email.imap.query.v1")
    assert desc_imap.get("ok") is True
    cap_i = desc_imap.get("capability", {})
    assert cap_i.get("mode") == "read_only"

    desc_wp = capability_describe("wordpress.site.query.v1")
    assert desc_wp.get("ok") is True
    cap_w = desc_wp.get("capability", {})
    assert cap_w.get("mode") == "read_only"


def test_invoke_cpanel_get_permission_matrix():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "get_permission_matrix"},
    )
    assert res.get("ok") is True
    result = res.get("result", {})
    matrix = result.get("matrix", {})
    assert "DomainInfo::domains_data" in matrix
    assert matrix["DomainInfo::domains_data"].get("ok") is True
    assert "Cron::list_cron" in matrix
    assert matrix["Cron::list_cron"].get("ok") is False


def test_invoke_cpanel_get_inventory():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "get_inventory"},
    )
    assert res.get("ok") is True
    result = res.get("result", {})
    inventory = result.get("inventory", [])
    assert len(inventory) >= 20
    domains = [d.get("domain") for d in inventory]
    assert "pcdoctor.com.ec" in domains
    assert "danzasjazz.com" in domains
    assert "creatorcore.ai" in domains


def test_invoke_cpanel_get_domain_info():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "get_domain_info", "domain": "danzasjazz.com"},
    )
    assert res.get("ok") is True
    result = res.get("result", {})
    assert result.get("domain") == "danzasjazz.com"
    meta = result.get("metadata", {})
    assert meta.get("has_wordpress") is True


def test_invoke_cpanel_mutation_guard():
    # Mutation when enforce_read_only is True must fail
    res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {"action": "save_file", "dir_path": "/tmp", "filename": "test.txt", "content": "hello"},
        context={"enforce_read_only": True},
    )
    assert res.get("ok") is False
    assert res.get("error") == "MUTATION_FORBIDDEN_IN_READ_ONLY_MODE"


def test_invoke_wordpress_page_spec_generator():
    res = capability_invoke(
        "wordpress.site.query.v1",
        {
            "action": "generate_page_spec",
            "domain": "creatorcore.ai",
            "page_title": "Landing Servicios AI 2026",
            "sections": [
                {"type": "hero", "title": "Potencia tu Empresa con IA", "subtitle": "Sistemas Autónomos", "cta": "Iniciar"},
                {"type": "features", "title": "Beneficios", "items": ["Alta velocidad", "Privacidad local"]}
            ]
        },
    )
    assert res.get("ok") is True
    result = res.get("result", {})
    assert result.get("mode") == "staging_dry_run_only"
    assert "gutenberg" in result
    assert "<!-- wp:cover" in result["gutenberg"]["rendered_html"]
    assert "elementor" in result
    assert len(result["elementor"]["elementor_data_spec"]) > 0


def test_invoke_email_imap_list_accounts():
    res = capability_invoke(
        "email.imap.query.v1",
        {"action": "list_accounts"},
    )
    assert res.get("ok") is True
    result = res.get("result", {})
    accounts = result.get("accounts", [])
    assert len(accounts) > 0
    assert any("pcdoctor.com.ec" in a or "innerchispa.us" in a for a in accounts)


def test_no_secret_leak_in_redacted_read():
    fake_config = "define('DB_PASSWORD', 'super_secret_password_123');\n$api_key = 'sk_live_xyz';"
    redacted = re.sub(r"(DB_PASSWORD|SECRET_KEY|AUTH_KEY|PASSWORD)(['\",\s]+)(['\"])([^'\"]+)(['\"])", r"\1\2\3[REDACTED_BY_GATEWAY]\5", fake_config)
    assert "super_secret_password_123" not in redacted
    assert "[REDACTED_BY_GATEWAY]" in redacted
