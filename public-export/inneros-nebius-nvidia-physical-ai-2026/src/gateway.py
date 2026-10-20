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
from typing import Any, Dict


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def governed_reboot(
    device_ref: str,
    provider: str = "unifi",
    dry_run: bool = True,
    approval_token: str = "",
) -> Dict[str, Any]:
    if not dry_run and not approval_token.strip():
        return {
            "ok": False,
            "error": "approval_required",
            "message": "Live execution requires explicit owner approval.",
            "requires_approval": True,
            "dry_run": False,
        }

    return {
        "ok": True,
        "capability_id": "network.device.reboot.v1",
        "status": "STAGED_DRY_RUN" if dry_run else "EXECUTED",
        "dry_run": dry_run,
        "mutation_applied": not dry_run,
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
) -> Dict[str, Any]:
    if provider == "grandstream_gwn":
        return {
            "ok": False,
            "error": "provider_gap",
            "message": "Grandstream GWN Cloud API does not support per-port PoE cycle.",
            "supported_providers": ["unifi"],
        }

    if not dry_run and not approval_token.strip():
        return {
            "ok": False,
            "error": "approval_required",
            "message": "Live PoE cycling requires explicit owner approval.",
            "requires_approval": True,
            "dry_run": False,
        }

    return {
        "ok": True,
        "capability_id": "network.device.poe_cycle.v1",
        "status": "STAGED_DRY_RUN" if dry_run else "EXECUTED",
        "dry_run": dry_run,
        "mutation_applied": not dry_run,
        "switch_ref": switch_ref,
        "port": port,
        "provider": provider,
        "receipt_id": f"rcpt_{uuid.uuid4().hex[:12]}",
        "timestamp": now_iso(),
    }


def verify_recovery(
    device_ref: str,
    expected_status: str = "online",
) -> Dict[str, Any]:
    return {
        "ok": True,
        "capability_id": "network.device.verify_recovery.v1",
        "device_ref": device_ref,
        "recovered": True,
        "current_status": expected_status,
        "checks": [
            {"check": "ping", "status": "PASS", "latency_ms": 1.5},
            {"check": "port_link", "status": "UP", "speed_mbps": 1000},
        ],
        "timestamp": now_iso(),
    }
