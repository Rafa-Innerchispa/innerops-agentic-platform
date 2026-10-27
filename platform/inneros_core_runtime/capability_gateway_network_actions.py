"""Governed Physical AI Network Action Capabilities for InnerOS Capability Gateway.

Implements persistent capabilities:
- network.device.reboot.v1
- network.device.poe_cycle.v1
- network.device.verify_recovery.v1

Key Invariants:
1. Approval-gated: Live mutations (dry_run=False) fail-closed without explicit owner approval.
2. Dry-Run supported: All mutations simulate cleanly without touching physical hardware.
3. Idempotent: Every execution generates a deterministic receipt with audit provenance.
4. Honest provider gap: Unsupported vendors or operations return explicit provider_gap errors.
5. Preserves existing read-only discovery paths intact.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from inneros_core_runtime.capability_gateway import register_capability


SUPPORTED_PROVIDERS = ("unifi", "grandstream_gwn")
MUTATION_POLICY_NAME = "OWNER_APPROVAL_REQUIRED_FOR_LIVE_MUTATIONS"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_approved(parameters: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Accept only server-validated approval, never an arbitrary token string."""
    if context.get("owner_approved") is True:
        return True
    if context.get("approval_validated") is True and str(context.get("owner_approval_ref") or "").strip():
        return True
    validator = context.get("approval_validator")
    if callable(validator):
        candidate = str(
            parameters.get("approval_token")
            or parameters.get("owner_approval_ref")
            or ""
        ).strip()
        if candidate:
            validation = validator(candidate)
            return bool(
                validation is True
                or (isinstance(validation, dict) and validation.get("ok") is True)
            )
    return False


def _sanitize_receipt_details(value: Any) -> Any:
    """Remove credentials from receipts before they can reach logs or a frontend."""
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(marker in normalized for marker in ("password", "secret", "token", "credential", "private_key")):
                sanitized[str(key)] = "[REDACTED]"
            else:
                sanitized[str(key)] = _sanitize_receipt_details(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_receipt_details(item) for item in value]
    return value


def _generate_receipt(
    capability_id: str,
    action: str,
    device_ref: str,
    provider: str,
    dry_run: bool,
    status: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    timestamp = _now()
    raw_hash = f"{capability_id}:{action}:{device_ref}:{provider}:{dry_run}:{timestamp}"
    evidence_hash = hashlib.sha256(raw_hash.encode("utf-8")).hexdigest()
    evidence_mode = (
        "SIMULATED" if dry_run or status.startswith("STAGED_") or status.startswith("SIMULATED_")
        else "REAL" if status in {"EXECUTED", "RECOVERED"}
        else "BLOCKED"
    )
    return {
        "receipt_id": f"rcpt_{uuid.uuid4().hex[:12]}",
        "capability_id": capability_id,
        "action": action,
        "device_ref": device_ref,
        "provider": provider,
        "dry_run": dry_run,
        "status": status,
        "evidence_mode": evidence_mode,
        "evidence_hash": evidence_hash,
        "timestamp": timestamp,
        "details": _sanitize_receipt_details(details),
    }


# ----------------------------------------------------------------------
# 1. network.device.reboot.v1
# ----------------------------------------------------------------------

NETWORK_DEVICE_REBOOT_MANIFEST: Dict[str, Any] = {
    "capability_id": "network.device.reboot.v1",
    "version": "1.0.0",
    "title": "Governed Network Device Reboot Capability",
    "domain": "network",
    "risk_class": "high",
    "mode": "mutation",
    "description": (
        "Governed reboot of physical network devices (APs, switches, routers). "
        "Approval-gated for live execution; dry-run supported; honest provider gap for unsupported vendors."
    ),
    "keywords": ["network", "device", "reboot", "restart", "unifi", "grandstream", "gwn", "switch", "ap", "router"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "device_ref": {
                "type": "string",
                "description": "Target device identifier, IP, or MAC address.",
            },
            "provider": {
                "type": "string",
                "description": "Network infrastructure provider: 'unifi', 'grandstream_gwn'.",
            },
            "tenant_id": {"type": "string", "description": "Tenant identifier (default: 'pcdoctor_lab')."},
            "site_id": {"type": "string", "description": "Site identifier (default: 'home_pcdoctor_lab')."},
            "dry_run": {
                "type": "boolean",
                "default": True,
                "description": "If true, validates and stages the plan without physical hardware mutation.",
            },
            "approval_token": {
                "type": "string",
                "description": "Required for dry_run=False live mutations.",
            },
            "owner_approval_ref": {
                "type": "string",
                "description": "Optional human or ops authorization ticket reference.",
            },
            "reason": {
                "type": "string",
                "description": "Operational rationale for the reboot.",
            },
        },
        "required": ["device_ref"],
    },
    "required_scopes": ["ralfia:write"],
}


def network_device_reboot_handler(
    parameters: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute or simulate a governed device reboot."""
    device_ref = str(parameters.get("device_ref") or "").strip()
    if not device_ref:
        return {"ok": False, "error": "device_ref_required"}

    provider = str(parameters.get("provider") or "").strip().lower()
    dry_run = bool(parameters.get("dry_run", True))
    tenant_id = str(parameters.get("tenant_id") or "pcdoctor_lab").strip()
    site_id = str(parameters.get("site_id") or "home_pcdoctor_lab").strip()
    reason = str(parameters.get("reason") or "Automated recovery action").strip()

    # Provider inference if not supplied
    if not provider:
        d_lower = device_ref.lower()
        if any(m in d_lower for m in ("gwn", "gcc", "grandstream")):
            provider = "grandstream_gwn"
        elif any(m in d_lower for m in ("unifi", "ubnt", "u7", "udm", "usw")):
            provider = "unifi"
        else:
            provider = "unifi"  # default candidate

    # Honest provider gap check
    if provider not in SUPPORTED_PROVIDERS:
        receipt = _generate_receipt(
            capability_id="network.device.reboot.v1",
            action="reboot",
            device_ref=device_ref,
            provider=provider,
            dry_run=dry_run,
            status="UNSUPPORTED_PROVIDER",
            details={"error": "provider_gap", "supported_providers": list(SUPPORTED_PROVIDERS)},
        )
        return {
            "ok": False,
            "error": "provider_gap",
            "message": f"Provider '{provider}' is not supported for remote governed reboot.",
            "supported_providers": list(SUPPORTED_PROVIDERS),
            "evidence_receipt": receipt,
        }

    # Approval check for live mutation
    if not dry_run and not _is_approved(parameters, context):
        receipt = _generate_receipt(
            capability_id="network.device.reboot.v1",
            action="reboot",
            device_ref=device_ref,
            provider=provider,
            dry_run=False,
            status="BLOCKED_APPROVAL_REQUIRED",
            details={"policy": MUTATION_POLICY_NAME},
        )
        return {
            "ok": False,
            "error": "approval_required",
            "message": (
                f"Live device reboot for '{device_ref}' requires explicit owner approval. "
                "Provide 'approval_token' or 'owner_approval_ref', or run with dry_run=True."
            ),
            "requires_approval": True,
            "dry_run": False,
            "evidence_receipt": receipt,
        }

    # Dry-Run mode
    if dry_run:
        plan = {
            "action": "reboot",
            "provider": provider,
            "device_ref": device_ref,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "reason": reason,
            "staged_command": (
                "ap/reboot" if provider == "grandstream_gwn" else f"/v1/sites/{site_id}/devices/{device_ref}/reboot"
            ),
        }
        receipt = _generate_receipt(
            capability_id="network.device.reboot.v1",
            action="reboot",
            device_ref=device_ref,
            provider=provider,
            dry_run=True,
            status="STAGED_DRY_RUN",
            details=plan,
        )
        return {
            "ok": True,
            "status": "STAGED_DRY_RUN",
            "dry_run": True,
            "mutation_applied": False,
            "provider": provider,
            "device_ref": device_ref,
            "message": f"Reboot simulated successfully for '{device_ref}' via {provider}.",
            "plan": plan,
            "evidence_receipt": receipt,
        }

    # Live execution path (approved)
    try:
        if provider == "grandstream_gwn":
            from inneros_core_runtime import grandstream_gwn_client as gwn
            creds, err = gwn.load_gwn_credentials()
            if not creds:
                return {
                    "ok": False,
                    "error": "credentials_unavailable",
                    "detail": err or "GWN credentials not loaded",
                }
            network_id = int(parameters.get("network_id") or 0)
            res = gwn.device_reboot(
                creds,
                network_id,
                device_ref,
                dry_run=False,
                owner_approval_ref=str(parameters.get("owner_approval_ref") or "owner_approved"),
            )
            live_status = "EXECUTED" if res.get("ok") else "FAILED"
            receipt = _generate_receipt(
                capability_id="network.device.reboot.v1",
                action="reboot",
                device_ref=device_ref,
                provider=provider,
                dry_run=False,
                status=live_status,
                details=res,
            )
            return {
                "ok": res.get("ok", False),
                "status": live_status,
                "mutation_applied": res.get("ok", False),
                "provider": provider,
                "device_ref": device_ref,
                "result": res,
                "evidence_receipt": receipt,
            }
        elif provider == "unifi":
            executor = context.get("network_action_executor")
            if not callable(executor):
                receipt = _generate_receipt(
                    capability_id="network.device.reboot.v1",
                    action="reboot",
                    device_ref=device_ref,
                    provider=provider,
                    dry_run=False,
                    status="BLOCKED_PROVIDER_ADAPTER_REQUIRED",
                    details={"error": "provider_adapter_unavailable"},
                )
                return {
                    "ok": False,
                    "error": "provider_adapter_unavailable",
                    "message": "No live UniFi executor is connected; no device was restarted.",
                    "mutation_applied": False,
                    "provider": provider,
                    "device_ref": device_ref,
                    "evidence_receipt": receipt,
                }
            exec_details = executor(
                action="reboot",
                provider=provider,
                target=device_ref,
                parameters={"tenant_id": tenant_id, "site_id": site_id, "reason": reason},
            )
            if not isinstance(exec_details, dict) or exec_details.get("ok") is not True:
                receipt = _generate_receipt(
                    capability_id="network.device.reboot.v1",
                    action="reboot",
                    device_ref=device_ref,
                    provider=provider,
                    dry_run=False,
                    status="PROVIDER_EXECUTION_FAILED",
                    details=exec_details if isinstance(exec_details, dict) else {"error": "invalid_provider_response"},
                )
                return {
                    "ok": False,
                    "error": "provider_execution_failed",
                    "mutation_applied": False,
                    "provider": provider,
                    "device_ref": device_ref,
                    "evidence_receipt": receipt,
                }
            provider_receipt = exec_details.get("provider_receipt")
            if not isinstance(provider_receipt, dict) or provider_receipt.get("evidence_mode") != "REAL":
                receipt = _generate_receipt(
                    capability_id="network.device.reboot.v1",
                    action="reboot",
                    device_ref=device_ref,
                    provider=provider,
                    dry_run=False,
                    status="BLOCKED_PROVIDER_RECEIPT_REQUIRED",
                    details={"error": "provider_receipt_required"},
                )
                return {
                    "ok": False,
                    "error": "provider_receipt_required",
                    "mutation_applied": False,
                    "provider": provider,
                    "device_ref": device_ref,
                    "evidence_receipt": receipt,
                }
            live_status = "EXECUTED"
            receipt = _generate_receipt(
                capability_id="network.device.reboot.v1",
                action="reboot",
                device_ref=device_ref,
                provider=provider,
                dry_run=False,
                status=live_status,
                details=exec_details,
            )
            return {
                "ok": True,
                "status": live_status,
                "mutation_applied": True,
                "provider": provider,
                "device_ref": device_ref,
                "result": exec_details,
                "evidence_receipt": receipt,
            }
    except Exception as exc:
        receipt = _generate_receipt(
            capability_id="network.device.reboot.v1",
            action="reboot",
            device_ref=device_ref,
            provider=provider,
            dry_run=False,
            status="EXECUTION_EXCEPTION",
            details={"exception": str(exc)},
        )
        return {
            "ok": False,
            "error": "EXECUTION_FAILED",
            "detail": str(exc),
            "evidence_receipt": receipt,
        }

    return {"ok": False, "error": "unhandled_provider_path"}


# ----------------------------------------------------------------------
# 2. network.device.poe_cycle.v1
# ----------------------------------------------------------------------

NETWORK_DEVICE_POE_CYCLE_MANIFEST: Dict[str, Any] = {
    "capability_id": "network.device.poe_cycle.v1",
    "version": "1.0.0",
    "title": "Governed PoE Port Power Cycle Capability",
    "domain": "network",
    "risk_class": "critical",
    "mode": "mutation",
    "description": (
        "Power-cycles a specific PoE switch port to hard-reboot attached physical equipment. "
        "Only supported on providers/hardware exposing per-port PoE control (e.g. UniFi switches). "
        "Approval-gated for live execution; returns honest provider_gap when unsupported."
    ),
    "keywords": ["network", "switch", "poe", "power", "cycle", "port", "unifi", "hard-reboot"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "switch_ref": {
                "type": "string",
                "description": "Switch IP, MAC, or identifier hosting the PoE port.",
            },
            "port": {
                "type": "integer",
                "description": "PoE port number to cycle (1-48).",
            },
            "provider": {
                "type": "string",
                "description": "Switch provider: 'unifi'. (Note: GWN Cloud does not expose per-port PoE cycle).",
            },
            "tenant_id": {"type": "string", "description": "Tenant identifier."},
            "site_id": {"type": "string", "description": "Site identifier."},
            "dry_run": {
                "type": "boolean",
                "default": True,
                "description": "Simulate PoE cycle without interrupting physical power.",
            },
            "approval_token": {
                "type": "string",
                "description": "Required for dry_run=False live execution.",
            },
            "owner_approval_ref": {
                "type": "string",
                "description": "Optional ticket reference for audit trace.",
            },
            "cycle_duration_seconds": {
                "type": "integer",
                "default": 10,
                "description": "Duration to hold PoE off before power restoration.",
            },
        },
        "required": ["switch_ref", "port"],
    },
    "required_scopes": ["ralfia:write"],
}


def network_device_poe_cycle_handler(
    parameters: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute or simulate a governed PoE port power cycle."""
    switch_ref = str(parameters.get("switch_ref") or parameters.get("device_ref") or "").strip()
    if not switch_ref:
        return {"ok": False, "error": "switch_ref_required"}

    try:
        port = int(parameters.get("port", 0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_port_number"}

    if port <= 0:
        return {"ok": False, "error": "port_must_be_positive_integer"}

    provider = str(parameters.get("provider") or "").strip().lower()
    if not provider:
        s_lower = switch_ref.lower()
        if "unifi" in s_lower or "usw" in s_lower:
            provider = "unifi"
        elif "gwn" in s_lower or "grandstream" in s_lower:
            provider = "grandstream_gwn"
        else:
            provider = "unifi"

    dry_run = bool(parameters.get("dry_run", True))
    duration = int(parameters.get("cycle_duration_seconds") or 10)

    # Honest provider gap check
    # Grandstream GWN Cloud does NOT expose per-port PoE cycle commands
    if provider == "grandstream_gwn":
        receipt = _generate_receipt(
            capability_id="network.device.poe_cycle.v1",
            action="poe_cycle",
            device_ref=f"{switch_ref}:port_{port}",
            provider=provider,
            dry_run=dry_run,
            status="UNSUPPORTED_PROVIDER_FEATURE",
            details={
                "error": "provider_gap",
                "detail": (
                    "Grandstream GWN Cloud API does not expose per-port PoE power cycle commands. "
                    "PoE cycling must be executed on the upstream managed switch (e.g. UniFi) or PDU."
                ),
                "supported_providers_for_poe_cycle": ["unifi"],
            },
        )
        return {
            "ok": False,
            "error": "provider_gap",
            "message": (
                "Grandstream GWN Cloud API does not support per-port PoE power cycling. "
                "Use upstream UniFi managed switch or local PDU."
            ),
            "provider": provider,
            "supported_providers": ["unifi"],
            "evidence_receipt": receipt,
        }

    if provider != "unifi":
        receipt = _generate_receipt(
            capability_id="network.device.poe_cycle.v1",
            action="poe_cycle",
            device_ref=f"{switch_ref}:port_{port}",
            provider=provider,
            dry_run=dry_run,
            status="UNSUPPORTED_PROVIDER",
            details={"error": "provider_gap", "supported_providers": ["unifi"]},
        )
        return {
            "ok": False,
            "error": "provider_gap",
            "message": f"Provider '{provider}' is not supported for PoE cycling.",
            "supported_providers": ["unifi"],
            "evidence_receipt": receipt,
        }

    # Approval check for live mutation
    if not dry_run and not _is_approved(parameters, context):
        receipt = _generate_receipt(
            capability_id="network.device.poe_cycle.v1",
            action="poe_cycle",
            device_ref=f"{switch_ref}:port_{port}",
            provider=provider,
            dry_run=False,
            status="BLOCKED_APPROVAL_REQUIRED",
            details={"policy": MUTATION_POLICY_NAME},
        )
        return {
            "ok": False,
            "error": "approval_required",
            "message": (
                f"PoE cycle on {switch_ref} port {port} cuts physical power and requires owner approval."
            ),
            "requires_approval": True,
            "dry_run": False,
            "evidence_receipt": receipt,
        }

    # Dry-Run mode
    if dry_run:
        plan = {
            "action": "poe_cycle",
            "provider": "unifi",
            "switch_ref": switch_ref,
            "port": port,
            "hold_off_seconds": duration,
            "staged_call": f"cmd/devmgr:power-cycle (port {port})",
        }
        receipt = _generate_receipt(
            capability_id="network.device.poe_cycle.v1",
            action="poe_cycle",
            device_ref=f"{switch_ref}:port_{port}",
            provider=provider,
            dry_run=True,
            status="STAGED_DRY_RUN",
            details=plan,
        )
        return {
            "ok": True,
            "status": "STAGED_DRY_RUN",
            "dry_run": True,
            "mutation_applied": False,
            "provider": "unifi",
            "switch_ref": switch_ref,
            "port": port,
            "message": f"PoE power cycle simulated on switch '{switch_ref}' port {port} (duration {duration}s).",
            "plan": plan,
            "evidence_receipt": receipt,
        }

    # Live execution (approved) requires a connected provider executor.  A
    # constructed dictionary is not proof that power was actually cycled.
    executor = context.get("network_action_executor")
    if not callable(executor):
        receipt = _generate_receipt(
            capability_id="network.device.poe_cycle.v1",
            action="poe_cycle",
            device_ref=f"{switch_ref}:port_{port}",
            provider="unifi",
            dry_run=False,
            status="BLOCKED_PROVIDER_ADAPTER_REQUIRED",
            details={"error": "provider_adapter_unavailable"},
        )
        return {
            "ok": False,
            "error": "provider_adapter_unavailable",
            "message": "No live UniFi PoE executor is connected; power was not changed.",
            "mutation_applied": False,
            "provider": "unifi",
            "switch_ref": switch_ref,
            "port": port,
            "evidence_receipt": receipt,
        }
    exec_details = executor(
        action="poe_cycle",
        provider="unifi",
        target=switch_ref,
        parameters={"port": port, "cycle_duration_seconds": duration},
    )
    if not isinstance(exec_details, dict) or exec_details.get("ok") is not True:
        receipt = _generate_receipt(
            capability_id="network.device.poe_cycle.v1",
            action="poe_cycle",
            device_ref=f"{switch_ref}:port_{port}",
            provider="unifi",
            dry_run=False,
            status="PROVIDER_EXECUTION_FAILED",
            details=exec_details if isinstance(exec_details, dict) else {"error": "invalid_provider_response"},
        )
        return {
            "ok": False,
            "error": "provider_execution_failed",
            "mutation_applied": False,
            "evidence_receipt": receipt,
        }
    provider_receipt = exec_details.get("provider_receipt")
    if not isinstance(provider_receipt, dict) or provider_receipt.get("evidence_mode") != "REAL":
        receipt = _generate_receipt(
            capability_id="network.device.poe_cycle.v1",
            action="poe_cycle",
            device_ref=f"{switch_ref}:port_{port}",
            provider="unifi",
            dry_run=False,
            status="BLOCKED_PROVIDER_RECEIPT_REQUIRED",
            details={"error": "provider_receipt_required"},
        )
        return {
            "ok": False,
            "error": "provider_receipt_required",
            "mutation_applied": False,
            "evidence_receipt": receipt,
        }
    receipt = _generate_receipt(
        capability_id="network.device.poe_cycle.v1",
        action="poe_cycle",
        device_ref=f"{switch_ref}:port_{port}",
        provider="unifi",
        dry_run=False,
        status="EXECUTED",
        details=exec_details,
    )
    return {
        "ok": True,
        "status": "EXECUTED",
        "mutation_applied": True,
        "provider": "unifi",
        "switch_ref": switch_ref,
        "port": port,
        "result": exec_details,
        "evidence_receipt": receipt,
    }


# ----------------------------------------------------------------------
# 3. network.device.verify_recovery.v1
# ----------------------------------------------------------------------

NETWORK_DEVICE_VERIFY_RECOVERY_MANIFEST: Dict[str, Any] = {
    "capability_id": "network.device.verify_recovery.v1",
    "version": "1.0.0",
    "title": "Network Device Recovery Verification Capability",
    "domain": "network",
    "risk_class": "low",
    "mode": "read_only",
    "description": (
        "Post-mutation verification of network device reachability, telemetry, and operating state. "
        "Verifies that a rebooted or PoE-cycled device has recovered healthy connectivity."
    ),
    "keywords": ["network", "device", "verify", "recovery", "health", "ping", "reachability", "post-reboot"],
    "parameters_schema": {
        "type": "object",
        "properties": {
            "device_ref": {
                "type": "string",
                "description": "Device IP, MAC, or identifier to verify.",
            },
            "provider": {
                "type": "string",
                "description": "Provider adapter: 'unifi', 'grandstream_gwn', or 'device_fabric'.",
            },
            "expected_status": {
                "type": "string",
                "default": "online",
                "description": "Target state to verify ('online', 'connected').",
            },
            "max_wait_seconds": {
                "type": "integer",
                "default": 30,
                "description": "Timeout threshold for recovery observation.",
            },
            "tenant_id": {"type": "string", "description": "Tenant identifier."},
            "site_id": {"type": "string", "description": "Site identifier."},
            "mock_probe": {
                "type": "boolean",
                "default": False,
                "description": "For offline testing, simulate probe success.",
            },
        },
        "required": ["device_ref"],
    },
    "required_scopes": ["ralfia:read"],
}


def network_device_verify_recovery_handler(
    parameters: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    """Verify post-reboot recovery and connectivity of a network device."""
    device_ref = str(parameters.get("device_ref") or "").strip()
    if not device_ref:
        return {"ok": False, "error": "device_ref_required"}

    provider = str(parameters.get("provider") or "device_fabric").strip().lower()
    expected = str(parameters.get("expected_status") or "online").strip().lower()
    max_wait = int(parameters.get("max_wait_seconds") or 30)
    mock_probe = bool(parameters.get("mock_probe", False))

    started_at = _now()
    checks: List[Dict[str, Any]] = []

    if mock_probe:
        checks.append({
            "check": "simulated_network_reachability",
            "target": device_ref,
            "status": "SIMULATED_PASS",
            "timestamp": _now(),
        })
        recovered = True
        current_status = expected
        verification_mode = "SIMULATED"
    else:
        probe = context.get("recovery_probe")
        if not callable(probe):
            receipt = _generate_receipt(
                capability_id="network.device.verify_recovery.v1",
                action="verify_recovery",
                device_ref=device_ref,
                provider=provider,
                dry_run=False,
                status="BLOCKED_PROVIDER_PROBE_REQUIRED",
                details={"error": "provider_probe_unavailable", "expected_status": expected},
            )
            return {
                "ok": False,
                "error": "provider_probe_unavailable",
                "message": "No real recovery probe is connected; recovery was not verified.",
                "recovered": False,
                "verification_mode": "NOT_VERIFIED",
                "device_ref": device_ref,
                "provider": provider,
                "current_status": "unknown",
                "expected_status": expected,
                "checks": [],
                "evidence_receipt": receipt,
            }
        probe_result = probe(
            device_ref=device_ref,
            provider=provider,
            expected_status=expected,
            max_wait_seconds=max_wait,
        )
        if not isinstance(probe_result, dict):
            probe_result = {"ok": False, "error": "invalid_probe_response"}
        checks = list(probe_result.get("checks") or [])
        recovered = bool(probe_result.get("ok") and probe_result.get("recovered"))
        current_status = str(probe_result.get("current_status") or "unknown")
        verification_mode = "REAL"

    receipt = _generate_receipt(
        capability_id="network.device.verify_recovery.v1",
        action="verify_recovery",
        device_ref=device_ref,
        provider=provider,
        dry_run=(verification_mode == "SIMULATED"),
        status=(
            "SIMULATED_RECOVERY" if verification_mode == "SIMULATED"
            else "RECOVERED" if recovered
            else "NOT_RECOVERED"
        ),
        details={
            "expected_status": expected,
            "recovered": recovered,
            "verification_mode": verification_mode,
            "checks": checks,
            "started_at": started_at,
            "completed_at": _now(),
        },
    )

    return {
        "ok": recovered,
        "recovered": recovered,
        "verification_mode": verification_mode,
        "device_ref": device_ref,
        "provider": provider,
        "current_status": current_status,
        "expected_status": expected,
        "checks": checks,
        "evidence_receipt": receipt,
    }


def register_network_action_capabilities() -> None:
    """Register all physical network action capabilities in Capability Gateway."""
    register_capability(NETWORK_DEVICE_REBOOT_MANIFEST, network_device_reboot_handler)
    register_capability(NETWORK_DEVICE_POE_CYCLE_MANIFEST, network_device_poe_cycle_handler)
    register_capability(NETWORK_DEVICE_VERIFY_RECOVERY_MANIFEST, network_device_verify_recovery_handler)
