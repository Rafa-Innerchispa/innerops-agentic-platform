"""
InnerOS Capability Gateway - Hosting & cPanel Subsystem v2.0.
Exposes canonical, typed MCP tools for cPanel hosting queries/mutations,
WordPress site diagnosis and remediation, and IMAP email inspection.
Integrates delegated grants, staging physical isolation, multi-domain support (all 24 domains),
and comprehensive audit logging.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List

from inneros_core_runtime.cpanel_client import CPanelClient, SecurityViolation
from inneros_core_runtime.hosting_authorization import (
    check_hosting_authorization,
    is_domain_mutation_allowed,
    record_hosting_audit_event,
    request_hosting_authorization,
    revoke_hosting_authorization,
    validate_hosting_authorization,
    get_all_account_domains,
)

CPANEL_HOSTING_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "hosting.cpanel.query.v1",
    "version": "1.3.0",
    "title": "cPanel Shared Hosting Live Inventory & Status Query",
    "domain": "hosting",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Audited live query tool for cPanel shared hosting: permission matrix, domains inventory (all 24 domains), file listing, safe file reading (with secret redaction), database integrity checks, disk quota & inodes, error logs, and authorization status. Safe for ChatGPT inspection.",
    "keywords": ["cpanel", "hosting", "inventory", "uapi", "domains", "security", "quota", "wordpress", "ssh"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "get_permission_matrix",
                    "get_inventory",
                    "list_domains",
                    "get_domain_info",
                    "get_domain_details",
                    "list_files",
                    "read_file",
                    "find_files",
                    "compare_files",
                    "list_databases",
                    "check_database",
                    "get_quota_info",
                    "list_backups",
                    "get_site_errors",
                    "tail_error_log",
                    "check_authorization",
                    "audit_domain_security",
                    "audit_account_security"
                ],
                "description": "Read-only inspection action to perform"
            },

            "domain": {"type": "string", "description": "Target domain (e.g. innerspark.live, industriasolex.com, pcdoctor.com.ec)"},
            "dir_path": {"type": "string", "description": "Directory path (relative to domain docroot or absolute)"},
            "filename": {"type": "string", "description": "Target filename to read"},
            "database": {"type": "string", "description": "Target database name for health check"},
            "pattern": {"type": "string", "description": "File search pattern (e.g. *.html, *.php)"},
            "auth_id": {"type": "string", "description": "Optional authorization grant ID to inspect"},
            "target_env": {"type": "string", "enum": ["staging", "production"], "default": "production"},
            "file1_path": {"type": "string"},
            "file2_path": {"type": "string"},
            "max_lines": {"type": "integer", "default": 40}
        },
        "required": ["action"],
    },
    "required_scopes": ["ralfia:read"],
}


def cpanel_hosting_query_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.hosting_control_plane import HostingControlPlane
    hcp = HostingControlPlane()
    action = str(parameters.get("action") or "").strip().lower()

    try:
        if action == "get_permission_matrix":
            return {"ok": True, "matrix": hcp.get_permission_matrix()}
        elif action in {"get_inventory", "list_domains"}:
            inv = hcp.get_domains_inventory()
            return {"ok": True, "inventory": inv, "total_domains": len(inv)}
        elif action in {"get_domain_info", "get_domain_details"}:
            domain = str(parameters.get("domain") or "").strip()
            if not domain:
                return {"ok": False, "error": "domain_required", "message": "Parameter 'domain' is required."}
            details = hcp.get_domain_details(domain)
            info = dict(details.get("metadata", {}))
            info["documentroot"] = details.get("docroot", info.get("docroot", ""))
            info["ip"] = "23.111.160.154"
            return {"ok": True, "domain": domain, "domain_info": info, "details": details}

        elif action == "list_files":
            domain = str(parameters.get("domain") or "").strip()
            dir_path = str(parameters.get("dir_path") or ".")
            target_env = str(parameters.get("target_env") or "production")
            return hcp.list_files(domain=domain, dir_path=dir_path, target_env=target_env)
        elif action == "read_file":
            domain = str(parameters.get("domain") or "").strip()
            dir_path = str(parameters.get("dir_path") or ".")
            filename = str(parameters.get("filename") or "").strip()
            target_env = str(parameters.get("target_env") or "production")
            if not filename:
                return {"ok": False, "error": "filename_required", "message": "Parameter 'filename' is required."}
            return hcp.read_file(domain=domain, dir_path=dir_path, filename=filename, target_env=target_env)
        elif action == "find_files":
            domain = str(parameters.get("domain") or "").strip()
            dir_path = str(parameters.get("dir_path") or ".")
            pattern = str(parameters.get("pattern") or "*")
            target_env = str(parameters.get("target_env") or "production")
            return hcp.find_files(domain=domain, dir_path=dir_path, pattern=pattern, target_env=target_env)
        elif action == "compare_files":
            domain = str(parameters.get("domain") or "").strip()
            f1 = str(parameters.get("file1_path") or "").strip()
            f2 = str(parameters.get("file2_path") or "").strip()
            return hcp.compare_files(domain=domain, file1_path=f1, file2_path=f2)
        elif action == "list_databases":
            dbs = hcp.client.list_databases()
            return {"ok": True, "databases": dbs, "count": len(dbs)}
        elif action == "check_database":
            db_name = str(parameters.get("database") or "").strip()
            if not db_name:
                return {"ok": False, "error": "database_required", "message": "Parameter 'database' is required."}
            res = hcp.client.check_database(db_name)
            return {"ok": True, "database": db_name, "result": res}
        elif action == "get_quota_info":
            quota = hcp.client.get_quota_info()
            return {"ok": True, "quota_info": quota}
        elif action == "list_backups":
            backups = hcp.client.list_backups()
            return {"ok": True, "backups": backups}
        elif action == "get_site_errors":
            domain = str(parameters.get("domain") or "").strip() or None
            errs = hcp.client.get_site_errors(domain=domain)
            return {"ok": True, "domain": domain, "errors": errs}
        elif action == "tail_error_log":
            domain = str(parameters.get("domain") or "").strip()
            dir_path = str(parameters.get("dir_path") or ".")
            max_lines = int(parameters.get("max_lines") or 40)
            target_dir = hcp.client.resolve_path(domain, dir_path, target_env="production")
            lines = hcp.client.tail_error_log(target_dir, max_lines=max_lines)
            return {"ok": True, "domain": domain, "lines_count": len(lines), "lines": lines}
        elif action == "check_authorization":
            auth_id = str(parameters.get("auth_id") or "").strip()
            domain = str(parameters.get("domain") or "").strip()
            return check_hosting_authorization(auth_id=auth_id, domain=domain)
        elif action == "audit_domain_security":
            domain = str(parameters.get("domain") or "").strip()
            if not domain:
                return {"ok": False, "error": "domain_required"}
            return hcp.audit_domain_security(domain)
        elif action == "audit_account_security":
            return hcp.audit_account_security()
        else:
            return {"ok": False, "error": f"unsupported_action: {action}"}
    except SecurityViolation as sv:
        return {"ok": False, "error": f"SECURITY_VIOLATION: {str(sv)}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


CPANEL_HOSTING_MUTATE_MANIFEST: Dict[str, Any] = {
    "capability_id": "hosting.cpanel.mutate.v1",
    "version": "1.3.0",
    "title": "cPanel Hosting Governed Mutate & Deployment System",
    "domain": "hosting",
    "risk_class": "high",
    "mode": "mutation",
    "description": "Governed mutation tool for cPanel hosting: request/check/revoke delegated authorization grants, directory creation, single/multi-file publishing with SHA-256 verification, staging deployment, release rollbacks, archive extraction, file chmod, and safe database repair. Staging changes are isolated; production mutations strictly enforce owner approvals.",
    "keywords": ["cpanel", "hosting", "mutation", "deploy", "staging", "publish", "rollback"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "request_authorization",
                    "check_authorization",
                    "revoke_authorization",
                    "create_directory",
                    "publish_file",
                    "save_file",
                    "publish_directory",
                    "upload_file",
                    "delete_file",
                    "remove_file",
                    "rename_file",
                    "move_file",
                    "chmod_file",
                    "extract_archive",
                    "deploy_release",
                    "rollback_release",
                    "repair_database",
                    "trigger_backup",
                    "update_seo_elements"
                ],
                "description": "Governed mutation action to perform"
            },
            "domain": {"type": "string", "description": "Target domain (e.g. innerspark.live, industriasolex.com, pcdoctor.com.ec)"},
            "target_env": {"type": "string", "enum": ["staging", "production"], "default": "staging"},
            "dir_path": {"type": "string", "description": "Relative directory path (e.g. '.' or 'assets' or subfolder)"},
            "filename": {"type": "string", "description": "Target filename"},
            "content": {"type": "string", "description": "Text or base64 file content"},
            "is_binary": {"type": "boolean", "default": False},
            "expected_sha256": {"type": "string"},
            "files": {"type": "array", "description": "List of {path, content, is_binary, sha256} for publish_directory/deploy"},
            "folder_name": {"type": "string", "description": "Folder name to create for create_directory"},
            "release_tag": {"type": "string", "description": "Release tag (e.g. v1.0.0)"},
            "auth_id": {"type": "string", "description": "Active delegated authorization grant ID"},
            "approval_token": {"type": "string", "description": "Owner approval token for production mutations"},
            "ttl_minutes": {"type": "integer", "default": 60},
            "reason": {"type": "string"},
            "archive_file": {"type": "string"},
            "dest_dir": {"type": "string"},
            "database": {"type": "string"},
            "mode": {"type": "string", "default": "0644"},
            "source_path": {"type": "string"},
            "dest_path": {"type": "string"},
            "seo_elements": {"type": "object"}
        },
        "required": ["action"],
    },
    "required_scopes": ["ralfia:write"],
}


def cpanel_hosting_mutate_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.hosting_control_plane import HostingControlPlane
    hcp = HostingControlPlane()
    action = str(parameters.get("action") or "").strip().lower()

    # Scope enforcement
    caller_scopes = set(context.get("scopes") or context.get("caller_scopes") or [])
    if "ralfia:write" not in caller_scopes:
        return {
            "ok": False,
            "error": "FORBIDDEN_SCOPE_WRITE_REQUIRED",
            "message": "Scope 'ralfia:write' is strictly required for hosting mutations."
        }

    domain = str(parameters.get("domain") or "").strip()
    target_env = str(parameters.get("target_env") or "staging").lower()
    auth_id = str(parameters.get("auth_id") or "").strip()
    approval_token = str(parameters.get("approval_token") or context.get("approval_token") or "").strip()

    # Special handling for Authorization management actions
    if action == "request_authorization":
        ttl = int(parameters.get("ttl_minutes") or 60)
        reason = str(parameters.get("reason") or "ChatGPT delegated hosting task")
        allowed_actions = parameters.get("allowed_actions")
        actor = str(context.get("actor") or "chatgpt")
        return request_hosting_authorization(
            domain=domain,
            target_env=target_env,
            ttl_minutes=ttl,
            allowed_actions=allowed_actions,
            reason=reason,
            approval_token=approval_token,
            actor=actor
        )
    elif action == "check_authorization":
        return check_hosting_authorization(auth_id=auth_id, domain=domain)
    elif action == "revoke_authorization":
        if not auth_id:
            return {"ok": False, "error": "auth_id_required"}
        return revoke_hosting_authorization(auth_id=auth_id)

    # For all operational mutations, validate active authorization grant
    if not domain:
        # Try inferring domain from dir_path if possible
        dir_p = str(parameters.get("dir_path") or "")
        for d in get_all_account_domains():
            if d in dir_p:
                domain = d
                break

    if target_env == "production":
        token_clean = str(approval_token or "").strip()
        if not token_clean or len(token_clean) < 8:
            return {
                "ok": False,
                "error": "APPROVAL_TOKEN_REQUIRED",
                "message": "Valid owner approval_token (min 8 chars) is strictly required for production mutations."
            }

    auth_val = validate_hosting_authorization(
        domain=domain,
        action=action,
        target_env=target_env,
        auth_id=auth_id,
        approval_token=approval_token,
        actor=str(context.get("actor") or "chatgpt")
    )

    if not auth_val.get("ok"):
        return auth_val

    active_auth_id = auth_val.get("auth_id", "")

    try:
        res: Dict[str, Any] = {}
        if action in {"publish_file", "save_file"}:
            dir_path = str(parameters.get("dir_path") or ".")
            filename = str(parameters.get("filename") or "")
            content = parameters.get("content")
            is_bin = bool(parameters.get("is_binary", False))
            exp_sha = parameters.get("expected_sha256")
            if not filename or content is None:
                return {
                    "ok": False,
                    "error": "dir_path_filename_content_required",
                    "message": "Parameters 'filename' and 'content' are required for publishing a file."
                }
            res = hcp.publish_file(
                domain=domain,
                dir_path=dir_path,
                filename=filename,
                content=content,
                is_binary=is_bin,
                expected_sha256=exp_sha,
                target_env=target_env
            )
        elif action == "create_directory":
            dir_path = str(parameters.get("dir_path") or ".")
            folder_name = str(parameters.get("folder_name") or parameters.get("name") or "")
            res = hcp.create_directory(domain=domain, dir_path=dir_path, folder_name=folder_name, target_env=target_env)
        elif action == "publish_directory":
            dir_path = str(parameters.get("dir_path") or ".")
            files = parameters.get("files") or []
            if not files:
                return {"ok": False, "error": "dir_path_and_files_required", "message": "List of 'files' is required."}
            res = hcp.publish_directory(domain=domain, dir_path=dir_path, files=files, target_env=target_env)
        elif action == "delete_file" or action == "remove_file":
            dir_path = str(parameters.get("dir_path") or ".")
            filename = str(parameters.get("filename") or "")
            res = hcp.delete_file(domain=domain, dir_path=dir_path, filename=filename, target_env=target_env)
        elif action == "rename_file" or action == "move_file":
            src = str(parameters.get("source_path") or "")
            dst = str(parameters.get("dest_path") or "")
            res = hcp.rename_file(domain=domain, source_path=src, dest_path=dst, target_env=target_env)
        elif action == "chmod_file":
            fp = str(parameters.get("file_path") or parameters.get("filename") or "")
            mode = str(parameters.get("mode") or "0644")
            res = hcp.chmod_file(domain=domain, file_path=fp, mode=mode, target_env=target_env)
        elif action == "extract_archive":
            archive = str(parameters.get("archive_file") or parameters.get("archive_path") or "").strip()
            dest = str(parameters.get("dest_dir") or ".").strip()
            res = hcp.extract_archive(domain=domain, archive_path=archive, dest_dir=dest, target_env=target_env)
        elif action == "deploy_release":
            release_tag = str(parameters.get("release_tag") or "v1.0.0").strip()
            files = parameters.get("files") or []
            if not files:
                return {"ok": False, "error": "files_required", "message": "List of 'files' is required."}
            res = hcp.deploy_release(domain=domain, release_tag=release_tag, files=files, target_env=target_env)
        elif action == "rollback_release":
            release_tag = str(parameters.get("release_tag") or "").strip()
            if not release_tag:
                return {"ok": False, "error": "release_tag_required"}
            res = hcp.rollback_release(domain=domain, release_tag=release_tag)
        elif action == "repair_database":
            db_name = str(parameters.get("database") or "").strip()
            if not db_name:
                return {"ok": False, "error": "database_required"}
            c_res = hcp.client.repair_database(db_name)
            res = {"ok": c_res.get("status") == 1, "database": db_name, "repair_result": c_res}
        elif action == "trigger_backup":
            c_res = hcp.client.trigger_backup()
            res = {"ok": c_res.get("status") == 1, "result": c_res}
        elif action == "update_seo_elements":
            elements = parameters.get("seo_elements") or {}
            res = hcp.update_seo_elements(domain=domain, elements=elements, target_env=target_env)
        else:
            return {"ok": False, "error": f"unsupported_action: {action}"}

        # Record audit event
        record_hosting_audit_event(
            auth_id=active_auth_id,
            action=action,
            details={"domain": domain, "target_env": target_env, "success": res.get("ok")}
        )
        return res
    except SecurityViolation as sv:
        return {"ok": False, "error": f"SECURITY_VIOLATION: {str(sv)}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


WORDPRESS_SITE_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "wordpress.site.query.v1",
    "version": "1.3.0",
    "title": "WordPress Site Inspection & Builder Spec Query",
    "domain": "wordpress",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Read-only WordPress diagnostic inspection: wp-config parser with secret redaction, database integrity check, recent error log tailing, Gutenberg/Elementor page builder spec generation, and live WP REST API inspection.",
    "keywords": ["wordpress", "diagnose", "gutenberg", "elementor", "plugins", "solex", "pcdoctor"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["diagnose_site", "get_page_spec", "query_rest"],
                "description": "WordPress query action"
            },
            "domain": {"type": "string", "description": "Target WordPress site domain (e.g. industriasolex.com, innerspark.live)"},
            "page_title": {"type": "string", "description": "Title for page spec generator"},
            "sections": {"type": "array", "description": "Sections layout for page builder spec"},
            "endpoint": {"type": "string", "default": "/wp-json/wp/v2/types"}
        },
        "required": ["action", "domain"],
    },
    "required_scopes": ["ralfia:read"],
}


def wordpress_site_query_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.hosting_control_plane import HostingControlPlane
    hcp = HostingControlPlane()
    action = str(parameters.get("action") or "").strip().lower()
    domain = str(parameters.get("domain") or "").strip()

    if not domain:
        return {"ok": False, "error": "domain_required"}

    try:
        if action == "diagnose_site":
            return hcp.diagnose_wordpress_site(domain)
        elif action == "get_page_spec":
            title = str(parameters.get("page_title") or f"Página {domain}")
            secs = parameters.get("sections")
            return hcp.generate_wordpress_page_spec(domain, title, secs)
        elif action == "query_rest":
            endpoint = str(parameters.get("endpoint") or "/wp-json/wp/v2/types")
            return hcp.query_wordpress_rest(domain, endpoint)
        else:
            return {"ok": False, "error": f"unsupported_action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


WORDPRESS_SITE_MUTATE_MANIFEST: Dict[str, Any] = {
    "capability_id": "wordpress.site.mutate.v1",
    "version": "1.3.0",
    "title": "WordPress Site Governed Mutate and Remediation",
    "domain": "wordpress",
    "risk_class": "high",
    "mode": "mutation",
    "description": "Governed WordPress mutation operations: database repair, plugin enabling/disabling (PHP crash recovery), and securing exposed backup files (chmod 0600). Requires ralfia:write scope.",
    "keywords": ["wordpress", "remediation", "repair", "plugins", "security", "industriasolex"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["repair_database", "toggle_plugin", "secure_exposed_files"],
                "description": "WordPress remediation action"
            },
            "domain": {"type": "string"},
            "plugin_slug": {"type": "string"},
            "enable": {"type": "boolean", "default": True},
            "approval_token": {"type": "string"}
        },
        "required": ["action", "domain"],
    },
    "required_scopes": ["ralfia:write"],
}


def wordpress_site_mutate_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.hosting_control_plane import HostingControlPlane
    hcp = HostingControlPlane()
    action = str(parameters.get("action") or "").strip().lower()
    domain = str(parameters.get("domain") or "").strip()

    if not domain:
        return {"ok": False, "error": "domain_required"}

    try:
        if action == "repair_database":
            return hcp.repair_wordpress_database(domain)
        elif action == "toggle_plugin":
            slug = str(parameters.get("plugin_slug") or "").strip()
            enable = bool(parameters.get("enable", True))
            return hcp.toggle_wordpress_plugin(domain, slug, enable)
        elif action == "secure_exposed_files":
            return hcp.secure_exposed_files(domain)
        else:
            return {"ok": False, "error": f"unsupported_action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


EMAIL_IMAP_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "email.imap.query.v1",
    "version": "1.3.0",
    "title": "IMAP Corporate Mailbox Safe Inspection",
    "domain": "email",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Safely queries corporate IMAP mailboxes using server-side credentials from owner_vault. Enforces strict tenant isolation (only authorized corporate accounts accessible, personal accounts blocked). Redacts passwords.",
    "keywords": ["email", "imap", "mailbox", "messages", "pcdoctor"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["query_inbox", "list_accounts"],
                "description": "IMAP action to perform"
            },
            "account": {"type": "string", "description": "Email address to query (e.g. info@pcdoctor.com.ec)"},
            "folder": {"type": "string", "default": "INBOX"},
            "max_messages": {"type": "integer", "default": 10}
        },
        "required": ["action"],
    },
    "required_scopes": ["ralfia:read"],
}


AUTHORIZED_CORPORATE_IMAP_ACCOUNTS = {
    "contabilidad@pcdoctor.com.ec",
    "facturacionelectronica@pcdoctor.com.ec",
    "info@innerspark.live",
    "info@pcdoctor.ai",
    "info@pcdoctor.com.ec",
    "rlopez@innerspark.live",
    "rlopez@pcdoctor.ai",
    "rlopez@pcdoctor.com.ec",
    "ventas@pcdoctor.com.ec",
    "ventas1@pcdoctor.com.ec",
}


def email_imap_query_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.hosting_control_plane import HostingControlPlane
    hcp = HostingControlPlane()
    action = str(parameters.get("action") or "query_inbox").strip().lower()

    if action == "list_accounts":
        return {
            "ok": True,
            "count": len(AUTHORIZED_CORPORATE_IMAP_ACCOUNTS),
            "accounts": sorted(list(AUTHORIZED_CORPORATE_IMAP_ACCOUNTS))
        }

    account = str(parameters.get("account") or "").strip().lower()
    if not account:
        return {"ok": False, "error": "account_required"}

    if account not in AUTHORIZED_CORPORATE_IMAP_ACCOUNTS:
        return {
            "ok": False,
            "error": "UNAUTHORIZED_MAILBOX_ACCESS_TENANT_ISOLATION",
            "account": account,
            "message": f"Access to mailbox '{account}' is restricted under tenant isolation policy."
        }

    folder = str(parameters.get("folder") or "INBOX")
    max_m = int(parameters.get("max_messages") or 10)
    return hcp.query_imap_mailbox(account=account, folder=folder, max_messages=max_m)


def register_hosting_capabilities() -> None:
    from inneros_core_runtime import capability_gateway as cg

    cg.register_capability(CPANEL_HOSTING_QUERY_MANIFEST, cpanel_hosting_query_handler)
    cg.register_capability(CPANEL_HOSTING_MUTATE_MANIFEST, cpanel_hosting_mutate_handler)
    cg.register_capability(WORDPRESS_SITE_QUERY_MANIFEST, wordpress_site_query_handler)
    cg.register_capability(WORDPRESS_SITE_MUTATE_MANIFEST, wordpress_site_mutate_handler)
    cg.register_capability(EMAIL_IMAP_QUERY_MANIFEST, email_imap_query_handler)

