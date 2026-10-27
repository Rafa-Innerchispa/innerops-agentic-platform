"""
Unit and integration tests for Universal Hosting Control Plane,
cPanel UAPI capabilities, IMAP query, WordPress spec generator,
and delegated domain-isolated hosting authorization.
Includes comprehensive validation for Acceptance Tests A through H.
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
from inneros_core_runtime.hosting_authorization import (
    request_hosting_authorization,
    validate_hosting_authorization,
    revoke_hosting_authorization,
    check_hosting_authorization,
)


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


# ======================================================================
# Mandatory Acceptance Tests: Pruebas A - H
# ======================================================================

def test_prueba_a_reading_solex_directly():
    """Prueba A: Lectura directa a Solex mediante el Capability Gateway."""
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


def test_prueba_b_mutation_rejected_without_authorization():
    """Prueba B: Una operacion sin autorizacion delegada debe ser rechazada."""
    # Attempting to save a file with a non-existent or fake auth_id
    res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "save_file",
            "domain": "innerspark.live",
            "dir_path": "/home/pcdoctor/public_html/innerspark.live",
            "filename": "unauthorized_test.txt",
            "content": "test",
            "auth_id": "hostauth_non_existent_fake_id_12345"
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "AUTHORIZATION_GRANT_NOT_FOUND"


def test_prueba_c_staging_deploy_with_authorization():
    """Prueba C: Una operacion de publicacion autorizada en staging debe completarse correctamente."""
    # 1. Request staging authorization
    auth_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "request_authorization",
            "domain": "innerspark.live",
            "target_env": "staging",
            "reason": "Prueba C: Staging deployment verification"
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    auth_info = auth_res.get("result", {})
    assert auth_info.get("ok") is True
    auth_id = auth_info.get("auth_id")
    assert str(auth_id).startswith("hostauth_")

    # 2. Deploy release in staging
    deploy_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "deploy_release",
            "domain": "innerspark.live",
            "release_tag": "v0.9.1-test",
            "target_env": "staging",
            "auth_id": auth_id,
            "files": [
                {"path": "index.html", "content": "<h1>InnerSpark Staging</h1>"},
                {"path": "styles/main.css", "content": "body { margin: 0; background: #000; }"}
            ]
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    deploy_info = deploy_res.get("result", {})
    assert deploy_info.get("ok") is True
    assert deploy_info.get("target_env") == "staging"
    assert deploy_info.get("published_count") == 2
    assert "manifest" in deploy_info


def test_prueba_d_rollback_release_verified():
    """Prueba D: Una publicacion debe poder revertirse sin perdida de datos."""
    # Issue grant for production with valid approval token
    auth_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "request_authorization",
            "domain": "innerspark.live",
            "target_env": "production",
            "approval_token": "owner_test_approval_token_12345",
            "reason": "Prueba D: Rollback validation"
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    auth_info = auth_res.get("result", {})
    assert auth_info.get("ok") is True
    auth_id = auth_info.get("auth_id")

    # Deploy release in production
    dep_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "deploy_release",
            "domain": "innerspark.live",
            "release_tag": "v0.9.2-rollback",
            "target_env": "production",
            "auth_id": auth_id,
            "approval_token": "owner_test_approval_token_12345",
            "files": [
                {"path": "version.txt", "content": "v0.9.2-test"}
            ]
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    assert dep_res.get("result", {}).get("ok") is True

    # Rollback release
    rb_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "rollback_release",
            "domain": "innerspark.live",
            "release_tag": "v0.9.2-rollback",
            "auth_id": auth_id,
            "approval_token": "owner_test_approval_token_12345"
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    rb_info = rb_res.get("result", {})
    assert rb_info.get("ok") is True
    assert rb_info.get("release_tag") == "v0.9.2-rollback"
    assert "snapshot_id" in rb_info


def test_prueba_e_vault_persistence_reusable_across_sessions():
    """Prueba E: Una sesion independiente debe reutilizar conexion del Vault sin pedir credenciales."""
    client = CPanelClient()  # Fresh client without passing token
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
            "dir_path": "/home/pcdoctor/public_html/industriasolex.com",
            "filename": "cross_test.txt",
            "content": "illegal cross domain write",
            "auth_id": auth_id
        },
        context={"scopes": ["ralfia:read", "ralfia:write"]},
    )
    result = cross_res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "GRANT_DOMAIN_MISMATCH"

    # Attempt to target a domain outside allowed mutation domains (e.g. danzasjazz.com)
    unauthorized_domain_res = capability_invoke(
        "hosting.cpanel.mutate.v1",
        {
            "action": "publish_file",
            "domain": "danzasjazz.com",
            "dir_path": "/home/pcdoctor/public_html/danzasjazz.com",
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
            "dir_path": "/home/pcdoctor/public_html/innerspark.live/_test_media_dir",
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

    # Audit domain security check on industriasolex.com
    audit_res = capability_invoke(
        "hosting.cpanel.query.v1",
        {"action": "audit_domain_security", "domain": "industriasolex.com"}
    )
    assert audit_res.get("ok") is True
    audit = audit_res.get("result", {})
    assert audit.get("domain") == "industriasolex.com"
    assert audit.get("security_posture") == "CRITICAL"
    assert len(audit.get("exposed_backup_files", [])) >= 2


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
        {"action": "save_file", "dir_path": "/home/pcdoctor/public_html/innerspark.live", "filename": "test.txt", "content": "test"},
        context={"scopes": ["ralfia:read"]},  # Missing ralfia:write
    )
    result = res.get("result", {})
    assert result.get("ok") is False
    assert result.get("error") == "FORBIDDEN_SCOPE_WRITE_REQUIRED"


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
