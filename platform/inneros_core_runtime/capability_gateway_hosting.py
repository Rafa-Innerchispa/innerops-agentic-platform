"""
InnerOS Capability Gateway - Universal Hosting & cPanel Control Plane Capabilities.
Exposes hosting discovery, cPanel UAPI operations, IMAP mailbox queries, and WordPress specs.
"""

from __future__ import annotations

import os
from typing import Any, Dict
from typing import Any, Dict


CPANEL_HOSTING_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "hosting.cpanel.query.v1",
    "version": "1.0.0",
    "title": "cPanel & WordPress Hosting Query (read-only)",
    "domain": "hosting",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Read-only query capability for primary cPanel hosting, addon domains, file listing, database inventory, SSL, PHP, disk quota, and permission matrix without expanding chatgpt_compact.",
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
        # Prevent secret leak: if sensitive config, redact password values
        if "wp-config" in filename.lower() or ".env" in filename.lower():
            import re
            content = re.sub(r"(DB_PASSWORD|SECRET_KEY|AUTH_KEY|PASSWORD)[^;,\n]*", r"\1: [REDACTED_BY_GATEWAY]", content)
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


CPANEL_HOSTING_MUTATE_MANIFEST: Dict[str, Any] = {
    "capability_id": "hosting.cpanel.mutate.v1",
    "version": "1.0.0",
    "title": "cPanel & WordPress Hosting Mutation",
    "domain": "hosting",
    "risk_class": "high",
    "mode": "mutation",
    "description": "Governed mutation capability for cPanel hosting: safe file saving and account backups with audit logging and rollback requirements.",
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

    if action == "save_file":
        dir_path = str(parameters.get("dir_path") or "")
        filename = str(parameters.get("filename") or "")
        content = str(parameters.get("content") or "")
        if not dir_path or not filename:
            return {"ok": False, "error": "dir_path_and_filename_required"}
        res = hcp.client.save_file_content(dir_path, filename, content)
        return {"ok": res.get("status") == 1, "result": res}
    elif action == "trigger_backup":
        res = hcp.client.trigger_backup()
        return {"ok": res.get("status") == 1, "result": res}
    else:
        return {"ok": False, "error": f"unsupported_action: {action}"}


EMAIL_IMAP_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "email.imap.query.v1",
    "version": "1.0.0",
    "title": "IMAP Mailbox Discovery and Search",
    "domain": "email",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Queries IMAP inbox, folders, quotas, and messages safely using server-side owner_vault credentials without leaking plain passwords.",
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
        from inneros_core_runtime import owner_vault
        res = owner_vault.list_owner_credentials()
        items = res.get("items", [])
        imap_accounts = [it.get("key") for it in items if it.get("category") == "email_imap"]
        return {"ok": True, "count": len(imap_accounts), "accounts": imap_accounts}
    elif action == "query_inbox":
        account = str(parameters.get("account") or "").strip().lower()
        if not account:
            return {"ok": False, "error": "account_required"}
        folder = str(parameters.get("folder") or "INBOX")
        limit = int(parameters.get("max_messages") or 15)
        return hcp.query_imap_mailbox(account, folder=folder, max_messages=limit)
    else:
        return {"ok": False, "error": f"unsupported_action: {action}"}


WORDPRESS_SITE_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "wordpress.site.query.v1",
    "version": "1.0.0",
    "title": "WordPress Site Inspection and Landing Page Spec Generator",
    "domain": "wordpress",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Inspects WordPress sites, plugins, themes, and generates typed Gutenberg and Elementor JSON specs in safe dry-run staging mode.",
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
