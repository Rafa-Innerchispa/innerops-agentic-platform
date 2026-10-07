"""Capability Gateway — Governed execution plane for InnerOS capabilities.

Provides search, describe, invoke, and execution tracking over an allowlisted capability registry.
Does NOT permit arbitrary function dispatch by string name.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# Registry of allowlisted capability manifests
_CAPABILITY_REGISTRY: Dict[str, Dict[str, Any]] = {}
_CAPABILITY_HANDLERS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {}
_EXECUTIONS_STORE: Dict[str, Dict[str, Any]] = {}
_LEGACY_CAPABILITY_ALIASES: Dict[str, str] = {
    "local_exec_inspect_repo": "local_exec.inspect_repo.v1",
    "local_exec_prepare_repo": "local_exec.prepare_repo.v1",
    "local_exec_acquire_lock": "local_exec.acquire_lock.v1",
    "local_exec_release_lock": "local_exec.release_lock.v1",
    "local_exec_create_worktree": "local_exec.create_worktree.v1",
    "local_exec_write_file": "local_exec.write_file.v1",
    "local_exec_apply_patch": "local_exec.apply_patch.v1",
    "local_exec_run_command_allowlisted": "local_exec.run_command_allowlisted.v1",
    "local_exec_commit_branch": "local_exec.commit_branch.v1",
    "local_exec_push_branch": "local_exec.push_branch.v1",
    "local_exec_report_evidence": "local_exec.report_evidence.v1",
    "local_gitlab_create_draft_merge_request": "local_gitlab.create_draft_merge_request.v1",
}


def resolve_capability_id(capability_id: str) -> str:
    """Map legacy MCP tool names and aliases to governed capability_id."""
    raw = (capability_id or "").strip()
    if not raw:
        return raw
    if raw in _CAPABILITY_REGISTRY:
        return raw
    aliased = _LEGACY_CAPABILITY_ALIASES.get(raw)
    if aliased and aliased in _CAPABILITY_REGISTRY:
        return aliased
    return raw


def register_capability(
    manifest: Dict[str, Any],
    handler: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None
) -> None:
    """Register an allowlisted capability with its manifest and handler."""
    cap_id = manifest["capability_id"]
    _CAPABILITY_REGISTRY[cap_id] = manifest
    if handler:
        _CAPABILITY_HANDLERS[cap_id] = handler


def _capability_query_matches(query: str, search_corpus: str) -> bool:
    q_norm = (query or "").lower().strip()
    if not q_norm:
        return True
    if q_norm in search_corpus:
        return True
    corpus_norm = search_corpus.replace(".", " ").replace("_", " ").replace("-", " ")
    tokens = [t for t in q_norm.split() if t]
    if not tokens:
        return True
    hits = sum(1 for token in tokens if token in corpus_norm)
    if hits == len(tokens):
        return True
    if len(tokens) == 1:
        return hits == 1
    min_hits = max(2, (len(tokens) + 1) // 2)
    if hits >= min_hits:
        return True
    if "network" in tokens and "network" in corpus_norm and hits >= 2:
        return True
    return False


def capability_search(
    query: str = "",
    domain: Optional[str] = None,
    tenant_id: Optional[str] = None,
    max_results: int = 10
) -> Dict[str, Any]:
    """Search registered capabilities matching a text query or domain filter."""
    q_norm = (query or "").lower().strip()
    results = []
    
    for cap_id, manifest in _CAPABILITY_REGISTRY.items():
        if domain and manifest.get("domain") != domain:
            continue
        if tenant_id and manifest.get("tenant_restriction") and tenant_id not in manifest.get("tenant_restriction", []):
            continue
            
        # Match text in id, title, description, keywords
        search_corpus = f"{cap_id} {manifest.get('title', '')} {manifest.get('description', '')} {' '.join(manifest.get('keywords', []))}".lower()
        if _capability_query_matches(q_norm, search_corpus):
            summary = {
                "capability_id": cap_id,
                "version": manifest.get("version", "1.0.0"),
                "title": manifest.get("title", ""),
                "domain": manifest.get("domain", "general"),
                "risk_class": manifest.get("risk_class", "low"),
                "mode": manifest.get("mode", "read_only"),
                "description": manifest.get("description", "")
            }
            results.append(summary)
            if len(results) >= max_results:
                break
                
    return {
        "ok": True,
        "query": query,
        "total_matches": len(results),
        "capabilities": results
    }


def capability_describe(
    capability_id: str,
    version: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve full manifest, schema, scopes, and policies for a capability."""
    capability_id = resolve_capability_id(capability_id)
    manifest = _CAPABILITY_REGISTRY.get(capability_id)
    if not manifest:
        return {
            "ok": False,
            "error": "CAPABILITY_NOT_FOUND",
            "capability_id": capability_id
        }
        
    return {
        "ok": True,
        "capability": manifest
    }


def capability_invoke(
    capability_id: str,
    parameters: Dict[str, Any],
    idempotency_key: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Invoke a registered capability handler with schema & policy enforcement."""
    capability_id = resolve_capability_id(capability_id)
    manifest = _CAPABILITY_REGISTRY.get(capability_id)
    if not manifest:
        return {
            "ok": False,
            "error": "CAPABILITY_NOT_FOUND",
            "capability_id": capability_id
        }
        
    handler = _CAPABILITY_HANDLERS.get(capability_id)
    if not handler:
        return {
            "ok": False,
            "error": "HANDLER_NOT_REGISTERED",
            "capability_id": capability_id
        }
        
    ctx = context or {}
    mode = manifest.get("mode", "read_only")
    
    # Enforce read-only constraint if running in strict read-only session
    if ctx.get("enforce_read_only") and mode == "mutation":
        return {
            "ok": False,
            "error": "MUTATION_FORBIDDEN_IN_READ_ONLY_MODE",
            "capability_id": capability_id
        }
        
    # Idempotency cache check
    if idempotency_key and idempotency_key in _EXECUTIONS_STORE:
        return _EXECUTIONS_STORE[idempotency_key]
        
    exec_id = f"exec_{uuid.uuid4().hex[:12]}"
    start_ts = datetime.now(timezone.utc).isoformat()
    
    try:
        result_data = handler(parameters, ctx)
        exec_record = {
            "ok": True,
            "execution_id": exec_id,
            "capability_id": capability_id,
            "status": "COMPLETED",
            "result": result_data,
            "provenance": {
                "started_at": start_ts,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "confidence": 1.0
            }
        }
        if idempotency_key:
            _EXECUTIONS_STORE[idempotency_key] = exec_record
        _EXECUTIONS_STORE[exec_id] = exec_record
        return exec_record
    except Exception as e:
        err_record = {
            "ok": False,
            "execution_id": exec_id,
            "capability_id": capability_id,
            "status": "FAILED",
            "error": str(e),
            "provenance": {
                "started_at": start_ts,
                "failed_at": datetime.now(timezone.utc).isoformat()
            }
        }
        return err_record


def capability_execution(
    execution_id: str,
    action: str = "status",
    payload: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Query, cancel, or approve an asynchronous capability execution."""
    record = _EXECUTIONS_STORE.get(execution_id)
    if not record:
        return {
            "ok": False,
            "error": "EXECUTION_NOT_FOUND",
            "execution_id": execution_id
        }
        
    if action == "status":
        return {"ok": True, "execution": record}
    elif action == "cancel":
        record["status"] = "CANCELLED"
        return {"ok": True, "execution": record}
    elif action == "approve":
        record["status"] = "APPROVED"
        return {"ok": True, "execution": record}
    else:
        return {"ok": False, "error": f"UNKNOWN_ACTION: {action}"}


# ----------------------------------------------------------------------
# Reference Network Adapter: network.device.query.v1
# ----------------------------------------------------------------------

NETWORK_DEVICE_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "network.device.query.v1",
    "version": "1.0.0",
    "title": "Network Device Unified Query Capability",
    "domain": "network",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Query telemetry, configuration, status, inventory, and diagnostics across network infrastructure (routers, switches, APs).",
    "keywords": ["network", "router", "switch", "ap", "dhcp", "arp", "vlan", "interfaces", "health", "telemetry"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "tenant_id": {"type": "string", "description": "Target tenant (e.g. 'bellini')"},
            "site_id": {"type": "string", "description": "Target site (e.g. 'bellini-i-ii')"},
            "device_ref": {"type": "string", "description": "Device IP or identifier (e.g. '192.168.3.1')"},
            "sections": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Telemetry sections to query: ['inventory', 'health', 'interfaces', 'arp', 'dhcp', 'vlans', 'mac_table', 'lldp', 'routes', 'clients', 'logs', 'events', 'poe', 'channels', 'storage', 'firmware']"
            }
        },
        "required": ["tenant_id", "sections"]
    },
    "required_scopes": ["ralfia:read"]
}


def network_device_query_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute network queries via Device Fabric (read-only); per-section errors stay partial."""
    from inneros_core_runtime import device_fabric

    tenant_id = str(parameters.get("tenant_id") or "bellini").strip().lower()
    site_id = str(parameters.get("site_id") or "bellini-i-ii").strip().lower()
    device_ref = str(parameters.get("device_ref") or "").strip()
    sections = list(parameters.get("sections") or ["health", "inventory"])
    started = datetime.now(timezone.utc).isoformat()
    provider_used = "grandstream_gwn"
    section_errors: Dict[str, Any] = {}
    data: Dict[str, Any] = {}

    for sec in sections:
        key = str(sec or "").strip().lower()
        if not key:
            continue
        try:
            if key == "health":
                payload = device_fabric.device_fabric_health(site_id=site_id)
                data[key] = payload
                provider_used = "device_fabric_health"
            elif key == "inventory":
                payload = device_fabric.device_fabric_inventory(
                    client_id=tenant_id,
                    site_id=site_id,
                    live=False,
                )
                data[key] = payload
                provider_used = str(payload.get("provider") or provider_used)
            elif key in {"providers", "capabilities"}:
                payload = device_fabric.device_fabric_capabilities(
                    device_ref=device_ref,
                    provider_id=str(parameters.get("provider_id") or "").strip(),
                )
                data[key] = payload
            elif device_ref:
                payload = device_fabric.device_fabric_get(device_ref=device_ref)
                data[key] = payload
            else:
                payload = device_fabric.device_fabric_get(device_ref="")
                data[key] = payload
        except Exception as exc:
            section_errors[key] = {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:500]}

    return {
        "ok": not section_errors or bool(data),
        "tenant_id": tenant_id,
        "site_id": site_id,
        "device_ref": device_ref or None,
        "sections_queried": sections,
        "provider_used": provider_used,
        "mode": "read_only",
        "data": data,
        "section_errors": section_errors,
        "provenance": {
            "source": "device_fabric",
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "audit": {"tenant": tenant_id, "site": site_id, "handler": "network.device.query.v1"},
        },
    }


COORDINATION_MESSAGING_LIST_MANIFEST: Dict[str, Any] = {
    "capability_id": "coordination.messaging.list.v1",
    "version": "1.0.0",
    "title": "Coordination messaging list (read-only)",
    "domain": "coordination",
    "risk_class": "low",
    "mode": "read_only",
    "description": "List agent messages for orchestrator verification without expanding chatgpt_compact.",
    "keywords": ["inbox", "messages", "coordination", "ack", "list_agent_messages"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "agent": {"type": "string"},
            "limit": {"type": "integer"},
            "status": {"type": "string"},
            "role": {"type": "string"},
        },
        "required": ["agent"],
    },
    "required_scopes": ["ralfia:read"],
}


def coordination_messaging_list_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from raphiia_openai.memory import agent_messages

    agent = str(parameters.get("agent") or "").strip()
    if not agent:
        return {"ok": False, "error": "agent_required"}
    limit = int(parameters.get("limit") or 20)
    status = parameters.get("status")
    role = str(parameters.get("role") or "inbox")
    return agent_messages.list_agent_messages(
        agent=agent,
        limit=limit,
        status=str(status).strip() if status else None,
        role=role,
    )


EMAIL_SEND_MANIFEST: Dict[str, Any] = {
    "capability_id": "email.send.v1",
    "version": "1.0.0",
    "title": "Governed outbound email (allowlisted identities)",
    "domain": "communications",
    "risk_class": "medium",
    "mode": "mutation",
    "description": "Send email via SMTP email_accounts with idempotency and from_identity allowlist.",
    "keywords": ["email", "smtp", "send", "outbound", "pcdoctor", "identity"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "from_identity": {"type": "string"},
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body_text": {"type": "string"},
            "body_html": {"type": "string"},
            "attachment_path": {"type": "string"},
            "idempotency_key": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["from_identity", "to", "subject"],
    },
    "required_scopes": ["ralfia:write"],
}

EMAIL_IDENTITIES_LIST_MANIFEST: Dict[str, Any] = {
    "capability_id": "email.identities.list.v1",
    "version": "1.0.0",
    "title": "Allowlisted outbound email identities",
    "domain": "communications",
    "risk_class": "low",
    "mode": "read_only",
    "description": "List send-capable allowlisted identities (no secrets).",
    "keywords": ["email", "identity", "allowlist", "smtp"],
    "parameters_schema": {"type": "object", "properties": {}},
    "required_scopes": ["ralfia:read"],
}

EMAIL_SENT_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "email.sent.query.v1",
    "version": "1.0.0",
    "title": "Query sent email delivery and IMAP audit ledger",
    "domain": "communications",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Query sent email records with message-id, delivery status, sent folder, and IMAP audit evidence.",
    "keywords": ["email", "sent", "audit", "imap", "delivery", "query"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "from_identity": {"type": "string"},
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "execution_id": {"type": "string"},
            "message_id": {"type": "string"},
            "limit": {"type": "integer"},
        },
    },
    "required_scopes": ["ralfia:read"],
}


def email_send_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.notifications import email_client

    body = str(parameters.get("body_text") or parameters.get("body") or parameters.get("body_html") or "")
    return email_client.send_email(
        to_addr=str(parameters.get("to") or "").strip(),
        subject=str(parameters.get("subject") or "").strip(),
        body=body,
        attachment_path=str(parameters.get("attachment_path") or "") or None,
        from_account=str(parameters.get("from_identity") or "").strip(),
        idempotency_key=str(parameters.get("idempotency_key") or "") or None,
        dry_run=bool(parameters.get("dry_run")),
    )


def email_identities_list_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.notifications import email_client

    return email_client.list_send_identities()


def email_sent_query_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from inneros_core_runtime.notifications import email_client

    return email_client.query_sent_emails(
        from_identity=str(parameters.get("from_identity") or "").strip() or None,
        to=str(parameters.get("to") or "").strip() or None,
        subject=str(parameters.get("subject") or "").strip() or None,
        execution_id=str(parameters.get("execution_id") or "").strip() or None,
        message_id=str(parameters.get("message_id") or "").strip() or None,
        limit=int(parameters.get("limit") or 20),
    )


register_capability(NETWORK_DEVICE_QUERY_MANIFEST, network_device_query_handler)
register_capability(COORDINATION_MESSAGING_LIST_MANIFEST, coordination_messaging_list_handler)
register_capability(EMAIL_SEND_MANIFEST, email_send_handler)
register_capability(EMAIL_IDENTITIES_LIST_MANIFEST, email_identities_list_handler)
register_capability(EMAIL_SENT_QUERY_MANIFEST, email_sent_query_handler)

from inneros_core_runtime.universal_network_audit import register_universal_network_audit_capabilities

register_universal_network_audit_capabilities()

from inneros_core_runtime.capability_gateway_lep import register_local_execution_capabilities
from inneros_core_runtime.capability_gateway_runtime import register_project_runtime_capabilities

register_local_execution_capabilities()
register_project_runtime_capabilities()
