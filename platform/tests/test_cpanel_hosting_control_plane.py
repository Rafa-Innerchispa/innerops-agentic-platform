"""
Unit and integration tests for Universal Hosting Control Plane,
cPanel UAPI capabilities, IMAP query, and WordPress spec generator.
Includes comprehensive adversarial security tests for path traversal,
scope enforcement, tenant isolation, secret redaction, staging release deployment,
integrity checking, and domain boundary mutation restrictions.
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
from inneros_core_runtime.cpanel_client import CPanelClient, SecurityViolation


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
    assert "wordpress.site.mutate.v1" in cap_ids_wp


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

    desc_wpm = capability_describe("wordpress.site.mutate.v1")
    assert desc_wpm.get("ok") is True
    cap_wm = desc_wpm.get("capability", {})
    assert cap_wm.get("mode") == "mutation"


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


def test_invoke_cpanel_get_inventory_exact_reconciliation():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "get_inventory"},
    )
    assert res.get("ok") is True
    result = res.get("result", {})
    inventory = result.get("inventory", [])
    assert len(inventory) == 24  # Exact 24 domains

    wp_sites = [d for d in inventory if d.get("has_wordpress")]
    non_wp_sites = [d for d in inventory if not d.get("has_wordpress")]

    assert len(wp_sites) == 11
    assert len(non_wp_sites) == 13
    assert len(wp_sites) + len(non_wp_sites) == 24


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


# Adversarial Security Tests
def test_path_traversal_attack_rejection():
    # Attempting to read /etc/passwd or traversal
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "read_file", "dir_path": "/home/pcdoctor/public_html/../../etc", "filename": "passwd"},
    )
    assert res.get("ok") is False
    assert "SECURITY_VIOLATION" in str(res)


def test_sensitive_file_read_rejection():
    # Attempting to read .env or ssh keys
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "read_file", "dir_path": "/home/pcdoctor/public_html", "filename": ".env"},
    )
    assert res.get("ok") is False
    assert "SECURITY_VIOLATION" in str(res)

    res2 = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "read_file", "dir_path": "/home/pcdoctor/public_html", "filename": "id_rsa"},
    )
    assert res2.get("ok") is False
    assert "SECURITY_VIOLATION" in str(res2)


def test_denied_extension_rejection():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "read_file", "dir_path": "/home/pcdoctor/public_html", "filename": "database_dump.sql"},
    )
    assert res.get("ok") is False
    assert "SECURITY_VIOLATION" in str(res)


def test_wp_config_deterministic_redaction():
    client = CPanelClient()
    sample_wp_config = (
        "define('DB_NAME', 'pcdoctor_wp');\n"
        "define('DB_USER', 'pcdoctor_admin');\n"
        "define('DB_PASSWORD', 'SuperSecret999!');\n"
        "define('AUTH_KEY', 'xK92#mPL123_token');\n"
        "define('NONCE_SALT', 'sAlT_99887766');\n"
    )
    sanitized = client._redact_secrets("wp-config.php", sample_wp_config)
    assert "SuperSecret999!" not in sanitized
    assert "xK92#mPL123_token" not in sanitized
    assert "sAlT_99887766" not in sanitized
    assert "[REDACTED_BY_GATEWAY]" in sanitized


def test_mutation_rejected_without_admin_scope():
    res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {"action": "save_file", "dir_path": "/home/pcdoctor/public_html/innerspark.live", "filename": "test.txt", "content": "test", "approval_token": "appr_12345678"},
        context={"scopes": ["ralfia:read", "ralfia:write"]},  # Missing ralfia:admin
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "FORBIDDEN_SCOPE_ADMIN_AND_WRITE_REQUIRED"


def test_mutation_rejected_without_approval_token():
    res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {"action": "save_file", "dir_path": "/home/pcdoctor/public_html/innerspark.live", "filename": "test.txt", "content": "test"},
        context={"scopes": ["ralfia:read", "ralfia:write", "ralfia:admin"]},  # Has scopes, but missing approval_token
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "APPROVAL_TOKEN_REQUIRED"


def test_domain_mutation_boundary_restricted():
    # Attempting mutation on a domain other than innerspark.live or industriasolex.com
    res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {"action": "save_file", "dir_path": "/home/pcdoctor/public_html/danzasjazz.com", "filename": "test.txt", "content": "test", "approval_token": "appr_12345678"},
        context={"scopes": ["ralfia:read", "ralfia:write", "ralfia:admin"]},
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "FORBIDDEN_DOMAIN_MUTATION_RESTRICTED"


def test_wordpress_mutate_boundary_restricted():
    res = capability_invoke(
        "wordpress.site.mutate.v1",
        {"action": "secure_exposed_files", "domain": "danzasjazz.com", "approval_token": "appr_12345678"},
        context={"scopes": ["ralfia:read", "ralfia:write", "ralfia:admin"]},
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "FORBIDDEN_DOMAIN_MUTATION_RESTRICTED"


def test_wordpress_mutate_rejected_without_approval_token():
    res = capability_invoke(
        "wordpress.site.mutate.v1",
        {"action": "secure_exposed_files", "domain": "industriasolex.com"},
        context={"scopes": ["ralfia:read", "ralfia:write", "ralfia:admin"]},
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "APPROVAL_TOKEN_REQUIRED"


def test_imap_tenant_isolation_rejects_unauthorized_account():
    # Attempting to query an unauthorized personal account
    res = capability_invoke(
        "email.imap.query.v1",
        {"action": "query_inbox", "account": "hrlg@hotmail.com"},
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "UNAUTHORIZED_MAILBOX_ACCESS_TENANT_ISOLATION"


def test_imap_tenant_isolation_allows_authorized_account():
    res = capability_invoke(
        "email.imap.query.v1",
        {"action": "list_accounts"},
    )
    result = res.get("result", {})
    assert result.get("ok") is True
    accounts = result.get("accounts", [])
    assert "info@pcdoctor.com.ec" in accounts
    assert "hrlg@hotmail.com" not in accounts
    assert "rafagye@gmail.com" not in accounts


def test_wordpress_page_spec_generator():
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


def test_diagnose_solex_wordpress_via_capability():
    res = capability_invoke(
        "wordpress.site.query.v1",
        {"action": "diagnose_site", "domain": "industriasolex.com"}
    )
    assert res.get("ok") is True
    diag = res.get("result", {})
    assert diag.get("domain") == "industriasolex.com"
    assert diag.get("wordpress_detected") is True
    assert diag.get("database_configuration", {}).get("db_name") == "pcdoctor_wp107"
    assert diag.get("database_integrity", {}).get("verified") is True
    assert diag.get("database_integrity", {}).get("tables_count") == 51


def test_cpanel_check_database_via_capability():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "check_database", "database": "pcdoctor_wp107"}
    )
    assert res.get("ok") is True
    assert res.get("result", {}).get("database") == "pcdoctor_wp107"
    check_res = res.get("result", {}).get("result", {})
    assert check_res.get("status") == 1


def test_cpanel_tail_error_log_via_capability():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "tail_error_log", "domain": "industriasolex.com", "max_lines": 10}
    )
    assert res.get("ok") is True
    assert "lines" in res.get("result", {})


def test_wordpress_call_wp_rest():
    res = capability_invoke(
        "wordpress.site.query.v1",
        {"action": "call_wp_rest", "domain": "danzasjazz.com", "endpoint": "/wp-json/wp/v2/types"}
    )
    assert res.get("ok") is True
    assert res.get("result", {}).get("status") == 200
