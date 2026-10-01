"""
InnerOS Core Runtime - Governed Capability Gateway
Correlation ID: bellini-capability-gateway-20260930

Provides unified discovery, schema retrieval, invocation, and asynchronous lifecycle
management for platform capabilities without expanding the public MCP tool footprint (<= 25 tools).
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable

from .adapters.base_adapter import (
    ALL_SECTIONS,
    VALID_STATES,
    STATE_MEASURED,
    STATE_CONFIGURED,
    STATE_OBSERVED,
    STATE_UNSUPPORTED,
    STATE_UNREACHABLE,
    STATE_UNKNOWN
)
from .adapters.adapter_registry import default_adapter_registry
from .bellini_incident_correlator import BelliniIncidentCorrelator

_CAPABILITY_REGISTRY: Dict[str, Dict[str, Any]] = {}
_CAPABILITY_HANDLERS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {}
_EXECUTIONS_STORE: Dict[str, Dict[str, Any]] = {}


def register_capability(
    manifest: Dict[str, Any],
    handler: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
) -> None:
    """Register a capability manifest and its internal execution handler."""
    cap_id = manifest["capability_id"]
    _CAPABILITY_REGISTRY[cap_id] = manifest
    _CAPABILITY_HANDLERS[cap_id] = handler


def capability_search(
    query: Optional[str] = None,
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
        if not q_norm or q_norm in search_corpus:
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
    mode = parameters.get("mode", manifest.get("mode", "read_only"))
    
    # Enforce strict read-only constraints
    if mode != "read_only" and manifest.get("mode") == "read_only":
        return {
            "ok": False,
            "error": "MUTATION_FORBIDDEN_IN_READ_ONLY_MODE",
            "capability_id": capability_id
        }
    if ctx.get("enforce_read_only") and manifest.get("mode") == "mutation":
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
# Reference Network Capability: network.device.query.v1
# ----------------------------------------------------------------------

NETWORK_DEVICE_QUERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "network.device.query.v1",
    "version": "1.0.0",
    "title": "Network Device Unified Query Capability",
    "domain": "network",
    "risk_class": "low",
    "mode": "read_only",
    "description": "Query telemetry, configuration, status, inventory, and diagnostics across network infrastructure (routers, switches, APs, CCTV).",
    "keywords": ["network", "router", "switch", "ap", "dhcp", "arp", "vlan", "interfaces", "health", "telemetry", "poe", "cctv"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "tenant": {"type": "string", "description": "Target tenant (default: 'bellini')", "default": "bellini"},
            "site": {"type": "string", "description": "Target site (default: 'bellini-i-ii')", "default": "bellini-i-ii"},
            "mode": {"type": "string", "enum": ["read_only"], "default": "read_only"},
            "device_ref": {"type": "string", "description": "Device IP or identifier (e.g. '192.168.3.1')"},
            "provider_hint": {"type": "string", "description": "Optional provider hint (e.g. 'grandstream_gcc', 'grandstream_gwn', 'hikvision', 'dahua')"},
            "sections": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Telemetry sections to query: {ALL_SECTIONS}"
            },
            "filters": {"type": "object", "description": "Optional query filters"},
            "include_raw_evidence": {"type": "boolean", "default": True},
            "timeout_seconds": {"type": "integer", "default": 30}
        },
        "required": ["device_ref"]
    },
    "required_scopes": ["ralfia:read"]
}


def network_device_query_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute network queries across allowed sections using AdapterRegistry."""
    tenant = parameters.get("tenant") or parameters.get("tenant_id", "bellini")
    site = parameters.get("site") or parameters.get("site_id", "bellini-i-ii")
    mode = parameters.get("mode", "read_only")
    device_ref = parameters.get("device_ref", "192.168.3.1")
    provider_hint = parameters.get("provider_hint")
    sections = parameters.get("sections") or ["inventory", "health"]
    filters = parameters.get("filters", {})
    include_raw_evidence = parameters.get("include_raw_evidence", True)
    timeout_seconds = parameters.get("timeout_seconds", 30)

    # Resolve adapter via registry
    adapter = default_adapter_registry.resolve_adapter(device_ref, provider_hint)
    
    return adapter.query(
        tenant=tenant,
        site=site,
        device_ref=device_ref,
        sections=sections,
        filters=filters,
        include_raw_evidence=include_raw_evidence,
        timeout_seconds=timeout_seconds,
        context=context
    )

# Register network.device.query.v1
register_capability(NETWORK_DEVICE_QUERY_MANIFEST, network_device_query_handler)
