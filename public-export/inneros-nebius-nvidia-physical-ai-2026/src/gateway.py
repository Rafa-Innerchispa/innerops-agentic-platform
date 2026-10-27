"""Governed Execution Gateway (Public Sanitized Edition).

Provides approval-gated physical network actions:
- reboot
- poe_cycle
- verify_recovery
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def governed_reboot(
    device_ref: str,
    provider: str = "unifi",
    dry_run: bool = True,
    approval_token: str = "",
    approval_validated: bool = False,
    executor: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not dry_run and (not approval_token.strip() or not approval_validated):
        return {
            "ok": False,
            "error": "approval_required",
            "message": "Live execution requires explicit owner approval.",
            "requires_approval": True,
            "dry_run": False,
        }

    if not dry_run and not callable(executor):
        return {
            "ok": False,
            "error": "provider_adapter_unavailable",
            "status": "BLOCKED_PROVIDER_ADAPTER_REQUIRED",
            "mutation_applied": False,
            "message": "Approval was present, but no live provider adapter is connected.",
        }
    if not dry_run:
        provider_result = executor(action="reboot", provider=provider, target=device_ref)
        provider_receipt = provider_result.get("provider_receipt") if isinstance(provider_result, dict) else None
        if not isinstance(provider_receipt, dict) or provider_receipt.get("evidence_mode") != "REAL":
            return {
                "ok": False,
                "error": "provider_receipt_required",
                "status": "BLOCKED_PROVIDER_RECEIPT_REQUIRED",
                "mutation_applied": False,
            }

    return {
        "ok": True,
        "capability_id": "network.device.reboot.v1",
        "status": "STAGED_DRY_RUN" if dry_run else "EXECUTED",
        "dry_run": dry_run,
        "mutation_applied": not dry_run,
        "evidence_mode": "SIMULATED" if dry_run else "REAL",
        "device_ref": device_ref,
        "provider": provider,
        "receipt_id": f"rcpt_{uuid.uuid4().hex[:12]}",
        "timestamp": now_iso(),
    }


def governed_poe_cycle(
    switch_ref: str,
    port: int,
    provider: str = "unifi",
    dry_run: bool = True,
    approval_token: str = "",
    approval_validated: bool = False,
    executor: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if provider == "grandstream_gwn":
        return {
            "ok": False,
            "error": "provider_gap",
            "message": "Grandstream GWN Cloud API does not support per-port PoE cycle.",
            "supported_providers": ["unifi"],
        }

    if not dry_run and (not approval_token.strip() or not approval_validated):
        return {
            "ok": False,
            "error": "approval_required",
            "message": "Live PoE cycling requires explicit owner approval.",
            "requires_approval": True,
            "dry_run": False,
        }

    if not dry_run and not callable(executor):
        return {
            "ok": False,
            "error": "provider_adapter_unavailable",
            "status": "BLOCKED_PROVIDER_ADAPTER_REQUIRED",
            "mutation_applied": False,
        }
    if not dry_run:
        provider_result = executor(
            action="poe_cycle",
            provider=provider,
            target=switch_ref,
            port=port,
        )
        provider_receipt = provider_result.get("provider_receipt") if isinstance(provider_result, dict) else None
        if not isinstance(provider_receipt, dict) or provider_receipt.get("evidence_mode") != "REAL":
            return {
                "ok": False,
                "error": "provider_receipt_required",
                "status": "BLOCKED_PROVIDER_RECEIPT_REQUIRED",
                "mutation_applied": False,
            }

    return {
        "ok": True,
        "capability_id": "network.device.poe_cycle.v1",
        "status": "STAGED_DRY_RUN" if dry_run else "EXECUTED",
        "dry_run": dry_run,
        "mutation_applied": not dry_run,
        "evidence_mode": "SIMULATED" if dry_run else "REAL",
        "switch_ref": switch_ref,
        "port": port,
        "provider": provider,
        "receipt_id": f"rcpt_{uuid.uuid4().hex[:12]}",
        "timestamp": now_iso(),
    }


def verify_recovery(
    device_ref: str,
    expected_status: str = "online",
    simulation: bool = False,
    probe: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if simulation:
        return {
            "ok": True,
            "capability_id": "network.device.verify_recovery.v1",
            "device_ref": device_ref,
            "recovered": True,
            "verification_mode": "SIMULATED",
            "current_status": expected_status,
            "checks": [{"check": "simulated_probe", "status": "SIMULATED_PASS"}],
            "timestamp": now_iso(),
        }
    if not callable(probe):
        return {
            "ok": False,
            "error": "provider_probe_unavailable",
            "recovered": False,
            "verification_mode": "NOT_VERIFIED",
            "current_status": "unknown",
            "timestamp": now_iso(),
        }
    result = probe(device_ref=device_ref, expected_status=expected_status)
    if not isinstance(result, dict):
        result = {"ok": False, "error": "invalid_probe_response"}
    recovered = bool(result.get("ok") and result.get("recovered"))
    return {
        "ok": recovered,
        "capability_id": "network.device.verify_recovery.v1",
        "device_ref": device_ref,
        "recovered": recovered,
        "verification_mode": "REAL",
        "current_status": str(result.get("current_status") or "unknown"),
        "checks": list(result.get("checks") or []),
        "timestamp": now_iso(),
    }
