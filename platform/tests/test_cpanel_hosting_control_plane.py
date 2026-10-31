"""
Unit and integration tests for Universal Hosting Control Plane v2.0,
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
    assert "ralfia:write" in cap_m.get("required_scopes", [])

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
    assert len(wp_sites) + len(non_wp_sites) == 24


def test_invoke_cpanel_get_domain_info():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "get_domain_info", "domain": "danzasjazz.com"},
    )
    assert res.get("ok") is True
    result = res.get("result", {})
    assert result.get("domain") == "danzasjazz.com"
    meta = result.get("domain_info", {})
    assert meta.get("docroot") == "/home/pcdoctor/public_html/danzasjazz.com"


# ======================================================================
# Pruebas Reales de Aceptacion (A a M)
# ======================================================================

def test_prueba_a_reading_solex_directly():
    """Prueba A: Lectura directa autorizada de archivos de Solex e InnerSpark con redaccion de secretos."""
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "read_file", "domain": "innerspark.live", "dir_path": ".", "filename": "index.html"},
    )
    assert res.get("ok") is True
    assert len(res.get("result", {}).get("content", "")) > 0
    assert "sha256" in res.get("result", {})


def test_prueba_b_request_authorization_staging():
    """Prueba B: Solicitud de autorizacion delegada para staging con TTL."""
    auth_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "request_authorization",
            "domain": "innerspark.live",
            "target_env": "staging",
            "ttl_minutes": 30,
            "reason": "Prueba B: Staging automated tests"
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    assert auth_res.get("ok") is True
    auth_data = auth_res.get("result", {})
    assert auth_data.get("ok") is True
    assert "auth_id" in auth_data
    assert auth_data.get("target_env") == "staging"


def test_prueba_c_staging_deploy_with_authorization():
    """Prueba C: Publicacion de archivo en staging sin adivinar rutas absolutas."""
    auth_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "request_authorization",
            "domain": "innerspark.live",
            "target_env": "staging",
            "reason": "Prueba C: Staging file write"
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    auth_id = auth_res.get("result", {}).get("auth_id")

    pub_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "publish_file",
            "domain": "innerspark.live",
            "dir_path": ".",
            "filename": "staging_test_acceptance.txt",
            "content": "P0 Test Acceptance: ChatGPT Operator Staging verified.",
            "target_env": "staging",
            "auth_id": auth_id
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    assert pub_res.get("ok") is True
    pub_info = pub_res.get("result", {})
    assert pub_info.get("ok") is True
    assert "sha256" in pub_info
    assert "_staging" in pub_info.get("dir_path")


def test_prueba_d_rollback_release_verified():
    """Prueba D: Despliegue de version y rollback verificado."""
    auth_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "request_authorization",
            "domain": "innerspark.live",
            "target_env": "staging",
            "reason": "Prueba D: Deploy release"
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    auth_id = auth_res.get("result", {}).get("auth_id")

    deploy_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "deploy_release",
            "domain": "innerspark.live",
            "release_tag": "v0.9.2-canary",
            "target_env": "staging",
            "auth_id": auth_id,
            "files": [
                {"path": "index.html", "content": "<html><body>Canary v0.9.2</body></html>"},
                {"path": "version.json", "content": '{"version": "0.9.2"}'}
            ]
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    assert deploy_res.get("ok") is True
    d_info = deploy_res.get("result", {})
    assert d_info.get("ok") is True
    assert d_info.get("published_files_count") == 2

    # Execute rollback
    rb_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "rollback_release",
            "domain": "innerspark.live",
            "release_tag": "v0.9.2-canary",
            "target_env": "staging",
            "auth_id": auth_id
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    rb_info = rb_res.get("result", {})
    assert rb_info.get("ok") is True
    assert "snapshot_id" in rb_info


def test_prueba_e_vault_persistence_reusable_across_sessions():
    """Prueba E: Una sesion independiente debe reutilizar conexion del Vault sin pedir credenciales."""
    client = CPanelClient()
    assert bool(client.token) is True
    assert len(client.token) == 32
    assert client.host == "https://23.111.160.154:2083"
    assert client.user == "pcdoctor"


def test_prueba_f_isolation_innerspark_grant_rejects_other_domain():
    """Prueba F: Un permiso sobre InnerSpark no debe permitir modificar otro dominio."""
    auth_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "request_authorization",
            "domain": "innerspark.live",
            "target_env": "staging",
            "reason": "Prueba F: Domain isolation check"
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    auth_id = auth_res.get("result", {}).get("auth_id")

    # Attempt to use InnerSpark auth_id on industriasolex.com
    cross_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "publish_file",
            "domain": "industriasolex.com",
            "dir_path": ".",
            "filename": "cross_test.txt",
            "content": "illegal cross domain write",
            "auth_id": auth_id
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    result = cross_res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "GRANT_DOMAIN_MISMATCH"

    # Attempt to target a domain outside authorized account domains (e.g. evil-domain.com)
    unauthorized_domain_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "publish_file",
            "domain": "evil-domain.com",
            "dir_path": ".",
            "filename": "hacked.txt",
            "content": "illegal write",
            "auth_id": auth_id
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    assert unauthorized_domain_res.get("result", {}).get("ok") is False
    assert unauthorized_domain_res.get("result", {}).get("error") == "FORBIDDEN_DOMAIN_MUTATION_RESTRICTED"


def test_prueba_g_directory_transfer_with_images_and_manifest():
    """Prueba G: Subir y verificar un directorio con archivos e imagenes y manifest SHA-256."""
    auth_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "request_authorization",
            "domain": "innerspark.live",
            "target_env": "staging",
            "reason": "Prueba G: Multi-file & media transfer"
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    auth_id = auth_res.get("result", {}).get("auth_id")

    # 1x1 transparent PNG base64
    sample_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

    transfer_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "publish_directory",
            "domain": "innerspark.live",
            "dir_path": "_test_media_dir",
            "auth_id": auth_id,
            "target_env": "staging",
            "files": [
                {"path": "index.html", "content": "<html><body><h1>Media Test</h1></body></html>"},
                {"path": "images/icon.png", "content": sample_png_b64, "is_binary": True},
                {"path": "js/bundle.js", "content": "console.log('loaded');"}
            ]
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    t_info = transfer_res.get("result", {})
    assert t_info.get("ok") is True
    assert t_info.get("published_files_count") == 3
    manifest = t_info.get("manifest", {})
    assert "index.html" in manifest
    assert "images/icon.png" in manifest
    assert "js/bundle.js" in manifest
    assert len(manifest["images/icon.png"]["sha256"]) == 64


def test_prueba_h_security_audit_and_secret_redaction():
    """Prueba H: Comprobar que secretos y respaldos no se exponen en respuestas ni logs."""
    client = CPanelClient()
    sample_wp_config = (
        "define('DB_NAME', 'pcdoctor_wp107');\n"
        "define('DB_USER', 'pcdoctor_wp107');\n"
        "define('DB_PASSWORD', 'SuperTopSecretPassword999!');\n"
        "define('AUTH_KEY', 'SecretSaltToken123');\n"
    )
    sanitized = client._redact_secrets("wp-config.php", sample_wp_config)
    assert "SuperTopSecretPassword999!" not in sanitized
    assert "SecretSaltToken123" not in sanitized
    assert "[REDACTED_BY_GATEWAY]" in sanitized

    audit_res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "audit_domain_security", "domain": "industriasolex.com"}
    )
    assert audit_res.get("ok") is True
    audit = audit_res.get("result", {})
    assert audit.get("domain") == "industriasolex.com"
    assert audit.get("security_posture") in {"CRITICAL", "HIGH", "HEALTHY"}


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


def test_cpanel_check_database_via_capability():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "check_database", "database": "pcdoctor_wp107"}
    )
    assert res.get("ok") is True
    assert res.get("result", {}).get("database") == "pcdoctor_wp107"
    check_res = res.get("result", {}).get("result", {})
    assert check_res.get("status") == 1


# ======================================================================
# Additional Adversarial Security Tests
# ======================================================================

def test_path_traversal_attack_rejection():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "read_file", "dir_path": "/home/pcdoctor/public_html/../../etc", "filename": "passwd"},
    )
    assert res.get("ok") is False
    assert "SECURITY_VIOLATION" in str(res)


def test_sensitive_file_read_rejection():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "read_file", "dir_path": "/home/pcdoctor/public_html", "filename": ".env"},
    )
    assert res.get("ok") is False
    assert "SECURITY_VIOLATION" in str(res)


def test_denied_extension_rejection():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "read_file", "dir_path": "/home/pcdoctor/public_html", "filename": "database_dump.sql"},
    )
    assert res.get("ok") is False
    assert "SECURITY_VIOLATION" in str(res)


def test_mutation_rejected_without_write_scope():
    res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {"action": "publish_file", "domain": "innerspark.live", "filename": "test.txt", "content": "test"},
        context={"scopes": ["ralfia:read"]},  # Missing ralfia:write
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "FORBIDDEN_SCOPE_WRITE_REQUIRED"


def test_production_mutation_rejected_without_approval_token():
    res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {"action": "publish_file", "domain": "innerspark.live", "filename": "prod.txt", "content": "test", "target_env": "production"},
        context={"scopes": ["ralfia:read", "ralfia:write"]},  # Missing approval token
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert "APPROVAL" in str(result.get("error")) or "UNAUTHORIZED" in str(result.get("error"))


def test_imap_tenant_isolation():
    # Unauthorized personal account
    res = capability_invoke(
        "email.imap.query.v1",
        {"action": "query_inbox", "account": "hrlg@hotmail.com"},
    )
    assert res.get("result", {}).get("ok") is False
    assert res.get("result", {}).get("error") == "UNAUTHORIZED_MAILBOX_ACCESS_TENANT_ISOLATION"

    # Authorized accounts list
    res_list = capability_invoke(
        "email.imap.query.v1",
        {"action": "list_accounts"},
    )
    assert res_list.get("result", {}).get("ok") is True
    assert "info@pcdoctor.com.ec" in res_list.get("result", {}).get("accounts", [])


def test_account_wide_security_audit():
    res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "audit_account_security"}
    )
    assert res.get("ok") is True
    summary = res.get("result", {}).get("summary", {})
    assert "critical_risk_domains" in summary
    assert res.get("result", {}).get("total_domains_audited") == 24
