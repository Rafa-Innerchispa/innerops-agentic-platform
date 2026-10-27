"""
InnerOS Capability Gateway - Universal Hosting & cPanel Control Plane Capabilities.
Hardened release with delegated domain-isolated authorizations, path traversal guards,
versioned staging deployments, secret redaction, and account-wide security auditing.
"""

from __future__ import annotations

import os
import hashlib
from typing import Any, Dict
from inneros_core_runtime.cpanel_client import SecurityViolation
from inneros_core_runtime.hosting_authorization import (
    ALLOWED_MUTATION_DOMAINS,
    is_domain_mutation_allowed,
    request_hosting_authorization,
    validate_hosting_authorization,
    record_hosting_audit_event,
    revoke_hosting_authorization,
    check_hosting_authorization,
)

# Authorized tenant mailboxes for IMAP query
AUTHORIZED_IMAP_ACCOUNTS = {
    "info@pcdoctor.com.ec",
    "ventas@pcdoctor.com.ec",
    "contabilidad@pcdoctor.com.ec",
}


CPANEL_HOSTING_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "hosting.cpanel.query.v1",
    "version": "1.3.0",
    "title": "cPanel & WordPress Hosting Query (read-only)",
    "domain": "hosting",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Read-only query capability for primary cPanel hosting, addon domains, file inspection (traversal-safe, redacted), database inventory, MySQL health checks, SSL, PHP, disk quota, site error logs, domain security audits, and permission matrix.",
    "keywords": ["cpanel", "wordpress", "hosting", "domains", "databases", "files", "ssl", "php", "quota", "logs", "audit", "security", "danzasjazz", "pcdoctor", "industriasolex", "innerspark"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "get_inventory",
                    "get_permission_matrix",
                    "list_domains",
                    "get_domain_info",
                    "list_files",
                    "read_file",
                    "list_databases",
                    "check_database",
                    "get_database_privileges",
                    "get_site_errors",
                    "tail_error_log",
                    "get_quota",
                    "list_mailboxes",
                    "list_ssl_hosts",
                    "list_backups",
                    "audit_domain_security",
                    "audit_account_security"
                ]
            },
            "domain": {"type": "string"},
            "dir_path": {"type": "string"},
            "filename": {"type": "string"},
            "database": {"type": "string"},
            "user": {"type": "string"},
            "max_lines": {"type": "integer"}
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
        if action == "get_inventory":
            inv = hcp.get_domains_inventory()
            return {"ok": True, "count": len(inv), "inventory": inv}
        elif action == "get_permission_matrix":
            return {"ok": True, "matrix": hcp.get_permission_matrix()}
        elif action == "list_domains":
            return hcp.client.list_domains()
        elif action == "get_domain_info":
            domain = str(parameters.get("domain") or "").strip()
            if not domain:
                return {"ok": False, "error": "domain_required"}
            res_details = hcp.get_domain_details(domain)
            meta = res_details.get("metadata", {})
            domain_info = {
                "domain": domain,
                "documentroot": meta.get("docroot", f"/home/pcdoctor/public_html/{domain}"),
                "ip": "23.111.160.154",
                "php_version": meta.get("php_version", "ea-php80"),
                "has_wordpress": meta.get("has_wordpress", False),
            }
            res_details["domain_info"] = domain_info
            return res_details
        elif action == "list_files":
            dir_path = str(parameters.get("dir_path") or "/home/pcdoctor/public_html")
            return {"ok": True, "dir_path": dir_path, "files": hcp.client.list_files(dir_path)}
        elif action == "read_file":
            dir_path = str(parameters.get("dir_path") or "")
            filename = str(parameters.get("filename") or "")
            if not dir_path or not filename:
                return {"ok": False, "error": "dir_path_and_filename_required"}
            content = hcp.client.get_file_content(dir_path, filename)
            return {"ok": True, "dir_path": dir_path, "filename": filename, "content": content}
        elif action == "list_databases":
            return {"ok": True, "databases": hcp.client.list_databases()}
        elif action == "check_database":
            db_name = str(parameters.get("database") or "").strip()
            if not db_name:
                return {"ok": False, "error": "database_required"}
            return {"ok": True, "database": db_name, "result": hcp.client.check_database(db_name)}
        elif action == "get_database_privileges":
            user = str(parameters.get("user") or "").strip()
            db_name = str(parameters.get("database") or "").strip()
            if not user or not db_name:
                return {"ok": False, "error": "user_and_database_required"}
            return {"ok": True, "user": user, "database": db_name, "result": hcp.client.get_database_privileges(user, db_name)}
        elif action == "get_site_errors":
            domain = str(parameters.get("domain") or "").strip() or None
            return {"ok": True, "domain": domain, "errors": hcp.client.get_site_errors(domain)}
        elif action == "tail_error_log":
            dir_path = str(parameters.get("dir_path") or "").strip()
            if not dir_path:
                domain = str(parameters.get("domain") or "").strip()
                if domain:
                    d_info = hcp.get_domain_details(domain)
                    dir_path = d_info.get("metadata", {}).get("docroot", "")
            if not dir_path:
                return {"ok": False, "error": "dir_path_or_domain_required"}
            max_lines = min(int(parameters.get("max_lines") or 40), 100)
            return {"ok": True, "dir_path": dir_path, "lines": hcp.client.tail_error_log(dir_path, max_lines)}
        elif action == "get_quota":
            return {"ok": True, "quota": hcp.client.get_quota_info()}
        elif action == "list_mailboxes":
            return {"ok": True, "mailboxes": hcp.client.list_pops()}
        elif action == "list_ssl_hosts":
            return {"ok": True, "ssl_hosts": hcp.client.list_ssl_hosts()}
        elif action == "list_backups":
            return {"ok": True, "backups": hcp.client.list_backups()}
        elif action == "audit_domain_security":
            domain = str(parameters.get("domain") or "").strip()
            if not domain:
                return {"ok": False, "error": "domain_required"}
            return hcp.audit_domain_security(domain)
        elif action == "audit_account_security":
            return hcp.audit_account_security()
        elif action == "check_authorization":
            auth_id = str(parameters.get("auth_id") or "").strip()
            domain = str(parameters.get("domain") or "").strip()
            return check_hosting_authorization(auth_id=auth_id, domain=domain)
        else:
            return {"ok": False, "error": f"unsupported_action: {action}"}
    except SecurityViolation as sv:
        return {"ok": False, "error": f"SECURITY_VIOLATION: {str(sv)}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


CPANEL_HOSTING_MUTATE_MANIFEST: Dict[str, Any] = {
    "capability_id": "hosting.cpanel.mutate.v1",
    "version": "1.3.0",
    "title": "cPanel & Web Hosting Governed Mutation and Release Manager",
    "domain": "hosting",
    "risk_class": "high",
    "mode": "mutation",
    "description": "Governed mutation operations (publish files, upload images/zip, versioned releases with staging, pre-deploy snapshot, and rollback) bounded strictly to innerspark.live and industriasolex.com. Supports time-bounded delegated authorization grants and requires owner approval for production mutations.",
    "keywords": ["cpanel", "ssh", "mutate", "save", "write", "backup", "restore", "publish", "deploy", "staging", "rollback", "authorization", "innerspark", "industriasolex"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "request_authorization",
                    "check_authorization",
                    "revoke_authorization",
                    "save_file",
                    "trigger_backup",
                    "publish_file",
                    "publish_directory",
                    "deploy_release",
                    "rollback_release",
                    "extract_archive",
                    "repair_database"
                ]
            },
            "domain": {"type": "string"},
            "dir_path": {"type": "string"},
            "filename": {"type": "string"},
            "content": {"type": "string"},
            "files": {"type": "array"},
            "is_binary": {"type": "boolean"},
            "expected_sha256": {"type": "string"},
            "release_tag": {"type": "string"},
            "target_env": {"type": "string", "enum": ["staging", "production"]},
            "archive_file": {"type": "string"},
            "dest_dir": {"type": "string"},
            "database": {"type": "string"},
            "approval_token": {"type": "string"},
            "auth_id": {"type": "string"},
            "ttl_minutes": {"type": "integer"},
            "reason": {"type": "string"},
            "allowed_actions": {"type": "array"}
        },
        "required": ["action"],
    },
    "required_scopes": ["ralfia:write"],
}


def cpanel_hosting_mutate_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.hosting_control_plane import HostingControlPlane
    hcp = HostingControlPlane()
    action = str(parameters.get("action") or "").strip().lower()

    # Read-only status checks do not require write mutation scope
    if action == "check_authorization":
        auth_id = str(parameters.get("auth_id") or "").strip()
        domain = str(parameters.get("domain") or "").strip()
        return check_hosting_authorization(auth_id=auth_id, domain=domain)

    # Scope check: ralfia:write or ralfia:admin is required
    caller_scopes = set(context.get("scopes") or context.get("caller_scopes") or [])
    if "ralfia:write" not in caller_scopes and "ralfia:admin" not in caller_scopes:
        return {
            "ok": False,
            "error": "FORBIDDEN_SCOPE_WRITE_REQUIRED",
            "message": "ralfia:write scope is strictly required for hosting mutations."
        }

    actor = str(context.get("client_id") or context.get("username") or "chatgpt")

    # 1. Authorization management actions
    if action == "request_authorization":
        domain = str(parameters.get("domain") or "").strip()
        target_env = str(parameters.get("target_env") or "staging").strip()
        ttl = int(parameters.get("ttl_minutes") or 60)
        reason = str(parameters.get("reason") or "Delegated hosting management")
        token = str(parameters.get("approval_token") or context.get("approval_token") or "").strip()
        actions = parameters.get("allowed_actions")
        return request_hosting_authorization(
            domain=domain,
            target_env=target_env,
            allowed_actions=actions,
            ttl_minutes=ttl,
            reason=reason,
            approval_token=token,
            actor=actor
        )
    elif action == "check_authorization":
        auth_id = str(parameters.get("auth_id") or "").strip()
        domain = str(parameters.get("domain") or "").strip()
        return check_hosting_authorization(auth_id=auth_id, domain=domain)
    elif action == "revoke_authorization":
        auth_id = str(parameters.get("auth_id") or "").strip()
        if not auth_id:
            return {"ok": False, "error": "auth_id_required"}
        return revoke_hosting_authorization(auth_id=auth_id, actor=actor)

    # 2. Domain resolution
    target_domain = str(parameters.get("domain") or "").strip()
    if not target_domain:
        dp = str(parameters.get("dir_path") or "").lower()
        for d in ALLOWED_MUTATION_DOMAINS:
            if d in dp:
                target_domain = d
                break

    # If domain cannot be inferred or is outside allowed mutation domains
    if not target_domain or not is_domain_mutation_allowed(target_domain):
        return {
            "ok": False,
            "error": "FORBIDDEN_DOMAIN_MUTATION_RESTRICTED",
            "target": target_domain or parameters.get("dir_path"),
            "allowed_domains": sorted(list(ALLOWED_MUTATION_DOMAINS)),
            "message": "Mutations are strictly restricted to innerspark.live and industriasolex.com."
        }

    # 3. Delegated Authorization Verification
    target_env = str(parameters.get("target_env") or ("staging" if (parameters.get("release_tag") or "_staging" in str(parameters.get("dir_path") or "") or "_test" in str(parameters.get("dir_path") or "")) else "production")).lower()
    auth_id = str(parameters.get("auth_id") or "").strip()
    token = str(parameters.get("approval_token") or context.get("approval_token") or "").strip()

    auth_val = validate_hosting_authorization(
        domain=target_domain,
        action=action,
        target_env=target_env,
        auth_id=auth_id,
        approval_token=token,
        actor=actor
    )
    if not auth_val.get("ok"):
        return auth_val

    active_auth_id = auth_val.get("auth_id", "")

    # 4. Execute mutation
    try:
        if action == "save_file":
            dir_path = str(parameters.get("dir_path") or "")
            filename = str(parameters.get("filename") or "")
            content = str(parameters.get("content") or "")
            if not dir_path or not filename:
                return {"ok": False, "error": "dir_path_and_filename_required"}

            try:
                prev_content = hcp.client.get_file_content(dir_path, filename)
                prev_hash = hashlib.sha256(prev_content.encode("utf-8")).hexdigest()
            except Exception:
                prev_content = ""
                prev_hash = "none"

            res = hcp.client.save_file_content(dir_path, filename, content)
            new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            record_hosting_audit_event(active_auth_id, action, {"dir_path": dir_path, "filename": filename, "sha256": new_hash})

            return {
                "ok": res.get("status") == 1,
                "result": res,
                "backup_receipt": {
                    "dir_path": dir_path,
                    "filename": filename,
                    "previous_sha256": prev_hash,
                    "new_sha256": new_hash,
                    "auth_id": active_auth_id
                }
            }
        elif action == "publish_file":
            dir_path = str(parameters.get("dir_path") or "")
            filename = str(parameters.get("filename") or "")
            content = parameters.get("content")
            is_bin = bool(parameters.get("is_binary", False))
            exp_sha = parameters.get("expected_sha256")
            if not dir_path or not filename or content is None:
                return {"ok": False, "error": "dir_path_filename_content_required"}
            res = hcp.publish_file(dir_path, filename, content, is_binary=is_bin, expected_sha256=exp_sha)
            if res.get("ok"):
                record_hosting_audit_event(active_auth_id, action, {"dir_path": dir_path, "filename": filename, "sha256": res.get("sha256")})
            return res
        elif action == "publish_directory":
            dir_path = str(parameters.get("dir_path") or "")
            files = parameters.get("files") or []
            if not dir_path or not files:
                return {"ok": False, "error": "dir_path_and_files_required"}
            res = hcp.publish_directory(dir_path, files)
            if res.get("ok"):
                record_hosting_audit_event(active_auth_id, action, {"dir_path": dir_path, "files_count": len(files)})
            return res
        elif action == "deploy_release":
            domain = target_domain
            release_tag = str(parameters.get("release_tag") or "v1.0.0").strip()
            files = parameters.get("files") or []
            if not files:
                return {"ok": False, "error": "files_required"}
            res = hcp.deploy_release(domain, release_tag, files, target_env=target_env)
            if res.get("ok"):
                record_hosting_audit_event(active_auth_id, action, {"domain": domain, "release_tag": release_tag, "target_env": target_env, "files_count": len(files)})
            return res
        elif action == "rollback_release":
            domain = target_domain
            release_tag = str(parameters.get("release_tag") or "").strip()
            if not release_tag:
                return {"ok": False, "error": "release_tag_required"}
            res = hcp.rollback_release(domain, release_tag)
            if res.get("ok"):
                record_hosting_audit_event(active_auth_id, action, {"domain": domain, "release_tag": release_tag})
            return res
        elif action == "extract_archive":
            archive = str(parameters.get("archive_file") or "").strip()
            dest = str(parameters.get("dest_dir") or "").strip()
            if not archive or not dest:
                return {"ok": False, "error": "archive_file_and_dest_dir_required"}
            res = hcp.client.extract_archive(archive, dest)
            return {"ok": res.get("cpanelresult", {}).get("data", [{}])[0].get("result") == 1, "result": res}
        elif action == "repair_database":
            db_name = str(parameters.get("database") or "").strip()
            if not db_name:
                return {"ok": False, "error": "database_required"}
            res = hcp.client.repair_database(db_name)
            if res.get("status") == 1:
                record_hosting_audit_event(active_auth_id, action, {"database": db_name})
            return {"ok": res.get("status") == 1, "database": db_name, "repair_result": res}
        elif action == "trigger_backup":
            res = hcp.client.trigger_backup()
            return {"ok": res.get("status") == 1, "result": res}
        else:
            return {"ok": False, "error": f"unsupported_action: {action}"}
    except SecurityViolation as sv:
        return {"ok": False, "error": f"SECURITY_VIOLATION: {str(sv)}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


WORDPRESS_SITE_MUTATE_MANIFEST: Dict[str, Any] = {
    "capability_id": "wordpress.site.mutate.v1",
    "version": "1.3.0",
    "title": "WordPress Site Governed Mutate and Remediation",
    "domain": "wordpress",
    "risk_class": "high",
    "mode": "mutation",
    "description": "Governed WordPress mutation operations: database repair, plugin enabling/disabling (PHP crash recovery), and securing exposed backup files (chmod 0600). Requires ralfia:write scope, authorized domain, and owner authorization grant / approval_token.",
    "keywords": ["wordpress", "remediation", "repair", "plugins", "security", "industriasolex", "innerspark"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["repair_database", "toggle_plugin", "secure_exposed_files"]
            },
            "domain": {"type": "string"},
            "plugin_slug": {"type": "string"},
            "enable": {"type": "boolean"},
            "approval_token": {"type": "string"},
            "auth_id": {"type": "string"}
        },
        "required": ["action", "domain"],
    },
    "required_scopes": ["ralfia:write"],
}


def wordpress_site_mutate_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.hosting_control_plane import HostingControlPlane
    hcp = HostingControlPlane()
    action = str(parameters.get("action") or "").strip().lower()
    domain = str(parameters.get("domain") or "").strip().lower()

    caller_scopes = set(context.get("scopes") or context.get("caller_scopes") or [])
    if "ralfia:write" not in caller_scopes and "ralfia:admin" not in caller_scopes:
        return {
            "ok": False,
            "error": "FORBIDDEN_SCOPE_WRITE_REQUIRED",
            "message": "ralfia:write scope is strictly required."
        }

    actor = str(context.get("client_id") or context.get("username") or "chatgpt")
    auth_id = str(parameters.get("auth_id") or "").strip()
    token = str(parameters.get("approval_token") or context.get("approval_token") or "").strip()

    auth_val = validate_hosting_authorization(
        domain=domain,
        action=action,
        target_env="production",
        auth_id=auth_id,
        approval_token=token,
        actor=actor
    )
    if not auth_val.get("ok"):
        return auth_val

    active_auth_id = auth_val.get("auth_id", "")

    try:
        if action == "repair_database":
            res = hcp.repair_wordpress_database(domain)
            record_hosting_audit_event(active_auth_id, action, {"domain": domain})
            return res
        elif action == "secure_exposed_files":
            res = hcp.secure_exposed_files(domain)
            record_hosting_audit_event(active_auth_id, action, {"domain": domain, "secured_count": res.get("secured_files_count")})
            return res
        elif action == "toggle_plugin":
            slug = str(parameters.get("plugin_slug") or "").strip()
            enable = bool(parameters.get("enable", True))
            if not slug:
                return {"ok": False, "error": "plugin_slug_required"}
            res = hcp.toggle_wordpress_plugin(domain, slug, enable)
            record_hosting_audit_event(active_auth_id, action, {"domain": domain, "plugin": slug, "enable": enable})
            return res
        else:
            return {"ok": False, "error": f"unsupported_action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


WORDPRESS_SITE_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "wordpress.site.query.v1",
    "version": "1.3.0",
    "title": "WordPress Site Inspection, Diagnostics, Spec Generator and REST Client",
    "domain": "wordpress",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Inspects WordPress site structure, plugins, themes, database integrity, error logs, security exposure of backups, queries WP REST API, and generates typed Gutenberg and Elementor JSON specs in safe dry-run staging mode without mutating production sites.",
    "keywords": ["wordpress", "gutenberg", "elementor", "diagnose", "landing", "rest", "builder", "industriasolex"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["generate_page_spec", "inspect_site", "diagnose_site", "call_wp_rest"]
            },
            "domain": {"type": "string"},
            "page_title": {"type": "string"},
            "sections": {"type": "array"},
            "endpoint": {"type": "string"}
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

    if action == "inspect_site":
        return hcp.get_domain_details(domain)
    elif action == "diagnose_site":
        return hcp.diagnose_wordpress_site(domain)
    elif action == "call_wp_rest":
        endpoint = str(parameters.get("endpoint") or "/wp-json/wp/v2/types")
        return hcp.query_wordpress_rest(domain, endpoint)
    elif action == "generate_page_spec":
        page_title = str(parameters.get("page_title") or f"Landing Page - {domain}")
        sections = parameters.get("sections")
        return hcp.generate_wordpress_page_spec(domain, page_title, sections=sections)
    else:
        return {"ok": False, "error": f"unsupported_action: {action}"}


EMAIL_IMAP_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "email.imap.query.v1",
    "version": "1.3.0",
    "title": "IMAP Mailbox Discovery and Search (Tenant Governed)",
    "domain": "email",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Queries IMAP inbox, folders, quotas, and messages safely for authorized tenant accounts using server-side owner_vault credentials. Enforces mailbox tenant isolation and redacts private data.",
    "keywords": ["email", "imap", "inbox", "search", "mailboxes", "folders"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["query_inbox", "list_accounts"]
            },
            "account": {"type": "string"},
            "folder": {"type": "string"},
            "max_messages": {"type": "integer"}
        },
        "required": ["action"],
    },
    "required_scopes": ["ralfia:read"],
}


def email_imap_query_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.hosting_control_plane import HostingControlPlane
    hcp = HostingControlPlane()
    action = str(parameters.get("action") or "").strip().lower()

    if action == "list_accounts":
        return {
            "ok": True,
            "count": len(AUTHORIZED_IMAP_ACCOUNTS),
            "accounts": sorted(list(AUTHORIZED_IMAP_ACCOUNTS)),
            "policy": "tenant_isolation_enforced"
        }
    elif action == "query_inbox":
        account = str(parameters.get("account") or "").strip().lower()
        if not account:
            return {"ok": False, "error": "account_required"}

        if account not in AUTHORIZED_IMAP_ACCOUNTS:
            return {
                "ok": False,
                "error": "UNAUTHORIZED_MAILBOX_ACCESS_TENANT_ISOLATION",
                "account": account,
                "message": f"Mailbox {account} is not in the authorized tenant list for this profile."
            }

        folder = str(parameters.get("folder") or "INBOX")
        limit = min(int(parameters.get("max_messages") or 10), 20)
        return hcp.query_imap_mailbox(account, folder=folder, max_messages=limit)
    else:
        return {"ok": False, "error": f"unsupported_action: {action}"}


def register_hosting_capabilities() -> None:
    from inneros_core_runtime.capability_gateway import register_capability
    register_capability(CPANEL_HOSTING_QUERY_MANIFEST, cpanel_hosting_query_handler)
    register_capability(CPANEL_HOSTING_MUTATE_MANIFEST, cpanel_hosting_mutate_handler)
    register_capability(WORDPRESS_SITE_QUERY_MANIFEST, wordpress_site_query_handler)
    register_capability(WORDPRESS_SITE_MUTATE_MANIFEST, wordpress_site_mutate_handler)
    register_capability(EMAIL_IMAP_QUERY_MANIFEST, email_imap_query_handler)
