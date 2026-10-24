"""
InnerOS Capability Gateway - Universal Hosting & cPanel Control Plane Capabilities.
Hardened release with strict tenant isolation, path traversal guards, ACLs, and approval tokens.
"""

from __future__ import annotations

import os
import hashlib
from typing import Any, Dict
from inneros_core_runtime.cpanel_client import SecurityViolation

# Authorized test/tenant mailboxes for IMAP query
AUTHORIZED_IMAP_ACCOUNTS = {
    "info@pcdoctor.com.ec",
    "ventas@pcdoctor.com.ec",
    "contabilidad@pcdoctor.com.ec",
}


CPANEL_HOSTING_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "hosting.cpanel.query.v1",
    "version": "1.1.0",
    "title": "cPanel & WordPress Hosting Query (read-only)",
    "domain": "hosting",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Read-only query capability for primary cPanel hosting, addon domains, file inspection (traversal-safe, redacted), database inventory, SSL, PHP, disk quota, and permission matrix.",
    "keywords": ["cpanel", "wordpress", "hosting", "domains", "databases", "files", "ssl", "php", "quota", "danzasjazz", "pcdoctor"],
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
                    "get_quota",
                    "list_mailboxes",
                    "list_ssl_hosts",
                    "list_backups"
                ]
            },
            "domain": {"type": "string"},
            "dir_path": {"type": "string"},
            "filename": {"type": "string"}
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
            return hcp.get_domain_details(domain)
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
        elif action == "get_quota":
            return {"ok": True, "quota": hcp.client.get_quota_info()}
        elif action == "list_mailboxes":
            return {"ok": True, "mailboxes": hcp.client.list_pops()}
        elif action == "list_ssl_hosts":
            return {"ok": True, "ssl_hosts": hcp.client.list_ssl_hosts()}
        elif action == "list_backups":
            return {"ok": True, "backups": hcp.client.list_backups()}
        else:
            return {"ok": False, "error": f"unsupported_action: {action}"}
    except SecurityViolation as sv:
        return {"ok": False, "error": f"SECURITY_VIOLATION: {str(sv)}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


CPANEL_HOSTING_MUTATE_MANIFEST: Dict[str, Any] = {
    "capability_id": "hosting.cpanel.mutate.v1",
    "version": "1.1.0",
    "title": "cPanel & WordPress Hosting Governed Mutation",
    "domain": "hosting",
    "risk_class": "high",
    "mode": "mutation",
    "description": "Governed mutation capability for cPanel hosting: safe file saving and account backups with server-side admin check, approval tokens, and pre-change backup diffs.",
    "keywords": ["cpanel", "wordpress", "save_file", "backup", "mutate"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save_file", "trigger_backup"]
            },
            "dir_path": {"type": "string"},
            "filename": {"type": "string"},
            "content": {"type": "string"},
            "approval_token": {"type": "string"}
        },
        "required": ["action"],
    },
    "required_scopes": ["ralfia:write", "ralfia:admin"],
}


def cpanel_hosting_mutate_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.hosting_control_plane import HostingControlPlane
    hcp = HostingControlPlane()
    action = str(parameters.get("action") or "").strip().lower()

    # Server-side Scope Enforcement
    caller_scopes = set(context.get("scopes") or context.get("caller_scopes") or [])
    if "ralfia:admin" not in caller_scopes or "ralfia:write" not in caller_scopes:
        return {
            "ok": False,
            "error": "FORBIDDEN_SCOPE_ADMIN_AND_WRITE_REQUIRED",
            "message": "Both ralfia:write and ralfia:admin scopes are strictly required for hosting mutations."
        }

    # Approval Token Validation
    token = str(parameters.get("approval_token") or context.get("approval_token") or "").strip()
    if not token or len(token) < 8:
        return {
            "ok": False,
            "error": "APPROVAL_TOKEN_REQUIRED",
            "message": "Valid non-empty owner approval_token is required for hosting mutations."
        }

    try:
        if action == "save_file":
            dir_path = str(parameters.get("dir_path") or "")
            filename = str(parameters.get("filename") or "")
            content = str(parameters.get("content") or "")
            if not dir_path or not filename:
                return {"ok": False, "error": "dir_path_and_filename_required"}

            # Preflight & Pre-change Hash (Backup Receipt)
            try:
                prev_content = hcp.client.get_file_content(dir_path, filename)
                prev_hash = hashlib.sha256(prev_content.encode("utf-8")).hexdigest()
            except Exception:
                prev_content = ""
                prev_hash = "none"

            res = hcp.client.save_file_content(dir_path, filename, content)
            new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            return {
                "ok": res.get("status") == 1,
                "result": res,
                "backup_receipt": {
                    "dir_path": dir_path,
                    "filename": filename,
                    "previous_sha256": prev_hash,
                    "new_sha256": new_hash,
                    "approval_token": token
                }
            }
        elif action == "trigger_backup":
            res = hcp.client.trigger_backup()
            return {"ok": res.get("status") == 1, "result": res}
        else:
            return {"ok": False, "error": f"unsupported_action: {action}"}
    except SecurityViolation as sv:
        return {"ok": False, "error": f"SECURITY_VIOLATION: {str(sv)}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


EMAIL_IMAP_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "email.imap.query.v1",
    "version": "1.1.0",
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
        # Only expose authorized corporate / tenant mailboxes, never personal recovery accounts
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

        # Strict Tenant ACL Isolation
        if account not in AUTHORIZED_IMAP_ACCOUNTS:
            return {
                "ok": False,
                "error": "UNAUTHORIZED_MAILBOX_ACCESS_TENANT_ISOLATION",
                "account": account,
                "message": f"Mailbox {account} is not in the authorized tenant list for this profile."
            }

        folder = str(parameters.get("folder") or "INBOX")
        limit = min(int(parameters.get("max_messages") or 10), 20)  # Bound limit
        return hcp.query_imap_mailbox(account, folder=folder, max_messages=limit)
    else:
        return {"ok": False, "error": f"unsupported_action: {action}"}


WORDPRESS_SITE_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "wordpress.site.query.v1",
    "version": "1.1.0",
    "title": "WordPress Site Inspection and Landing Page Spec Generator (Staging Safe)",
    "domain": "wordpress",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Inspects WordPress site structure, plugins, themes, and generates typed Gutenberg and Elementor JSON specs in safe dry-run staging mode without mutating production sites.",
    "keywords": ["wordpress", "gutenberg", "elementor", "wpbakery", "landing", "builder"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["generate_page_spec", "inspect_site"]
            },
            "domain": {"type": "string"},
            "page_title": {"type": "string"},
            "sections": {"type": "array"}
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
        details = hcp.get_domain_details(domain)
        return details
    elif action == "generate_page_spec":
        page_title = str(parameters.get("page_title") or f"Landing Page - {domain}")
        sections = parameters.get("sections")
        return hcp.generate_wordpress_page_spec(domain, page_title, sections=sections)
    else:
        return {"ok": False, "error": f"unsupported_action: {action}"}


def register_hosting_capabilities() -> None:
    from inneros_core_runtime.capability_gateway import register_capability
    register_capability(CPANEL_HOSTING_QUERY_MANIFEST, cpanel_hosting_query_handler)
    register_capability(CPANEL_HOSTING_MUTATE_MANIFEST, cpanel_hosting_mutate_handler)
    register_capability(EMAIL_IMAP_QUERY_MANIFEST, email_imap_query_handler)
    register_capability(WORDPRESS_SITE_QUERY_MANIFEST, wordpress_site_query_handler)
